package ai.zenagent

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardOpenOption
import java.time.Duration
import java.time.Instant

data class ToolCall(val id: String, val name: String, val arguments: String, val args: Map<String, Any?>) {
    /** The assistant turn must carry the call, and the tool turn must carry the matching id. */
    fun asAssistantEntry(): Map<String, Any?> = mapOf(
        "id" to id,
        "type" to "function",
        "function" to mapOf("name" to name, "arguments" to arguments),
    )
}

data class ChatMessage(
    val role: String,
    val content: String,
    val name: String? = null,
    val toolCallId: String? = null,
    val toolCalls: List<ToolCall> = emptyList(),
) {
    fun asMap(): Map<String, Any?> = buildMap {
        put("role", role)
        put("content", content)
        if (name != null) put("name", name)
        if (toolCallId != null) put("tool_call_id", toolCallId)
        if (toolCalls.isNotEmpty()) put("tool_calls", toolCalls.map { it.asAssistantEntry() })
    }
}

object Conversions {
    fun toAny(node: JsonValue?): Any? = when (node) {
        null, is JsonNull -> null
        is JsonObject -> node.entries.mapValues { toAny(it.value) }
        is JsonArray -> node.items.map { toAny(it) }
        is JsonString -> node.value
        is JsonNumber -> if (node.raw.contains('.') || node.raw.contains('e')) node.asDouble else node.asLong
        is JsonBool -> node.value
    }

    @Suppress("UNCHECKED_CAST")
    fun toMap(node: JsonValue?): Map<String, Any?> = (toAny(node) as? Map<String, Any?>) ?: emptyMap()
}

/** The agent loop (protocol §7): scripted (golden vectors) and live (real provider). */
object Agent {

    /**
     * Deterministic loop over a scripted transcript. Used by every runtime's conformance suite:
     * the gate and the tools are real, only the model is a script.
     */
    fun runScriptedLoop(script: List<JsonValue>, ctx: ToolContext): LoopOutcome {
        val tools = mutableListOf<String>()
        val results = mutableListOf<String>()
        var final = ""
        for (turn in script) {
            val call = turn.field("tool_call")
            if (call != null) {
                val name = call.field("name").stringOrNull() ?: continue
                val outcome = Tools.runTool(name, Conversions.toMap(call.field("args")), ctx)
                tools.add(name)
                results.add(outcome.result)
                continue
            }
            val finalNode = turn.field("final")
            if (finalNode is JsonString) {
                final = finalNode.value
                break
            }
        }
        return LoopOutcome(tools, results, final)
    }

    fun complete(
        decision: RouteDecision,
        messages: List<ChatMessage>,
        apiKey: String? = null,
        withTools: Boolean = false,
        timeoutSeconds: Long = 120,
    ): Pair<String, List<ToolCall>> {
        require(decision.status == "ok") { "cannot call provider: ${decision.errorCode}" }
        val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15)).build()
        val payload = mutableMapOf<String, Any?>("model" to decision.model, "messages" to messages.map { it.asMap() })
        val url: String
        if (decision.kind == "ollama-native") {
            url = "${decision.endpoint}/api/chat"
            payload["stream"] = false
        } else {
            url = "${decision.endpoint}/chat/completions"
            if (withTools) payload["tools"] = Tools.schema
        }
        val builder = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofSeconds(timeoutSeconds))
            .header("content-type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(jsonText(payload)))
        if (apiKey != null) {
            when (decision.authStyle) {
                "bearer" -> builder.header("authorization", "Bearer $apiKey")
                "x-api-key" -> builder.header("x-api-key", apiKey)
                "api-key" -> builder.header("api-key", apiKey)
            }
        }
        val response = client.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw RuntimeException("${decision.provider} ${response.statusCode()}: ${response.body().take(300)}")
        }
        val body = Json.parse(response.body())

        if (decision.kind == "ollama-native") {
            val content = body.field("message").field("content").stringOrNull() ?: ""
            return content to emptyList()
        }
        val message = body.field("choices").listOrNull()?.firstOrNull()?.field("message")
        val content = message.field("content").stringOrNull() ?: ""
        val calls = mutableListOf<ToolCall>()
        for (call in message.field("tool_calls").listOrNull() ?: emptyList()) {
            val function = call.field("function")
            val name = function.field("name").stringOrNull() ?: continue
            val rawArgs = function.field("arguments").stringOrNull() ?: "{}"
            val args = try { Conversions.toMap(Json.parse(rawArgs)) } catch (error: Exception) { mapOf("_raw" to rawArgs) }
            val id = call.field("id").stringOrNull() ?: "call_${calls.size}"
            calls.add(ToolCall(id, name, rawArgs, args))
        }
        return content to calls
    }

    /** Live loop: real model, real tools, real gate. Bounded by maxTurns. */
    fun runLiveLoop(
        decision: RouteDecision,
        prompt: String,
        ctx: ToolContext,
        apiKey: String? = null,
        maxTurns: Int = 6,
    ): LoopOutcome {
        val transcript = mutableListOf(
            ChatMessage("system", "You are zen-agent. Prefer calling a tool over guessing. Answer tersely."),
            ChatMessage("user", prompt),
        )
        val tools = mutableListOf<String>()
        val results = mutableListOf<String>()
        repeat(maxTurns) {
            val (content, calls) = complete(decision, transcript, apiKey, withTools = true)
            if (calls.isEmpty()) return LoopOutcome(tools, results, content.trim())
            transcript.add(ChatMessage("assistant", content, toolCalls = calls))
            for (call in calls) {
                val outcome = Tools.runTool(call.name, call.args, ctx)
                tools.add(call.name)
                results.add(outcome.result)
                transcript.add(ChatMessage("tool", outcome.result, name = call.name, toolCallId = call.id))
            }
        }
        return LoopOutcome(tools, results, "")
    }
}

/** Portable memory: newline-delimited JSON, no database, no lock-in. */
class MemoryStore(private val path: Path) {

    fun append(event: Map<String, Any?>): Map<String, Any?> {
        val record = LinkedHashMap<String, Any?>()
        record["ts"] = event["ts"] ?: Instant.now().toString()
        record.putAll(event)
        path.parent?.let { Files.createDirectories(it) }
        Files.writeString(path, jsonText(record) + "\n", StandardOpenOption.CREATE, StandardOpenOption.APPEND)
        return record
    }

    fun read(limit: Int = 20): List<JsonValue> {
        if (!Files.exists(path)) return emptyList()
        return Files.readAllLines(path).filter { it.isNotBlank() }.takeLast(limit).map { Json.parse(it) }
    }

    /** Cheap lexical recall: the events that mention the query words, most recent first. */
    fun recall(query: String, limit: Int = 5): List<JsonValue> {
        val words = query.lowercase().split(Regex("\\s+")).filter { it.length > 2 }
        return read(500).filter { event ->
            val haystack = event.render().lowercase()
            words.any { haystack.contains(it) }
        }.takeLast(limit).reversed()
    }
}

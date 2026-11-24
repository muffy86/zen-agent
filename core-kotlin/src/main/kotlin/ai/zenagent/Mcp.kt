package ai.zenagent

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * HTTP MCP transport (streamable HTTP with SSE replies).
 *
 * The device's own gateway exposes MCP over HTTP — http://127.0.0.1:8801/mcp/ (browser control) and
 * http://127.0.0.1:8802/mcp (Android control) — so nothing less than an HTTP client can reach the
 * most useful tools on this machine. The gateway returns an `mcp-session-id` header on `initialize`
 * and rejects later calls with "Bad Request: Missing session ID" unless it is echoed back.
 */
class McpHttpClient(private val url: String) {
    private val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15)).build()
    private var sessionId: String? = null
    private var nextId = 1

    private fun rpc(method: String, params: Any?, timeoutSeconds: Long = 30): JsonValue? {
        val id = nextId++
        val body = jsonText(mapOf("jsonrpc" to "2.0", "id" to id, "method" to method, "params" to params))
        val builder = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofSeconds(timeoutSeconds))
            .header("content-type", "application/json")
            .header("accept", "application/json, text/event-stream")
            .POST(HttpRequest.BodyPublishers.ofString(body))
        sessionId?.let { builder.header("mcp-session-id", it) }
        val response = client.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        response.headers().firstValue("mcp-session-id").ifPresent { sessionId = it }
        if (response.statusCode() !in 200..299) {
            throw RuntimeException("mcp http ${response.statusCode()}: ${response.body().take(200)}")
        }
        return extract(response.body(), id)
    }

    private fun extract(text: String, requestId: Int): JsonValue? {
        for (line in text.lines()) {
            val trimmed = line.trim()
            if (!trimmed.startsWith("data:")) continue
            val message = try { Json.parse(trimmed.removePrefix("data:").trim()) } catch (error: Exception) { continue }
            if ((message.field("id") as? JsonNumber)?.asLong == requestId.toLong()) return message
        }
        val whole = try { Json.parse(text) } catch (error: Exception) { return null }
        return if ((whole.field("id") as? JsonNumber)?.asLong == requestId.toLong()) whole else null
    }

    fun start(): McpHttpClient {
        sessionId = null // always begin a fresh session
        val init = rpc("initialize", mapOf(
            "protocolVersion" to "2025-06-18",
            "capabilities" to emptyMap<String, Any?>(),
            "clientInfo" to mapOf("name" to "zen-agent", "version" to "1.0.0"),
        ))
        require(init?.field("result") != null) { "mcp http initialize failed: ${init ?: "no response"}" }
        try { rpc("notifications/initialized", emptyMap<String, Any?>()) } catch (ignored: Exception) {
            // a notification may answer 202 with no body; that is not a failure
        }
        return this
    }

    fun listTools(): List<Pair<String, String>> {
        val response = rpc("tools/list", emptyMap<String, Any?>())
        return response?.field("result")?.field("tools")?.listOrNull()?.map {
            (it.field("name").stringOrNull() ?: "?") to (it.field("description").stringOrNull() ?: "")
        } ?: emptyList()
    }

    fun callTool(name: String, args: Map<String, Any?>): JsonValue? {
        val response = rpc("tools/call", mapOf("name" to name, "arguments" to args))
        response?.field("error")?.let { error ->
            throw RuntimeException("mcp tool error: ${error.field("message").stringOrNull()}")
        }
        return response?.field("result")
    }
}

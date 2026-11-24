package ai.zenagent

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Paths
import java.time.Duration
import kotlin.system.exitProcess

private fun loadRules(): PolicyRules {
    val doc = Json.parse(Files.readString(Paths2.fixtures().resolve("policy-cases.json")))
    return PolicyRules.from(doc.field("rules") ?: error("policy fixture has no 'rules' block"))
}

private fun flag(args: List<String>, name: String): String? {
    val index = args.indexOf("--$name")
    if (index < 0) return null
    val next = args.getOrNull(index + 1)
    return if (next == null || next.startsWith("--")) "" else next
}

private fun has(args: List<String>, name: String): Boolean = args.contains("--$name")

private fun requestFrom(args: List<String>): RouteRequest = RouteRequest(
    capability = flag(args, "capability"),
    prompt = flag(args, "prompt"),
    tags = flag(args, "tags")?.split(",") ?: emptyList(),
    prefer = flag(args, "prefer") ?: "balanced",
    providersAvailable = flag(args, "available")?.split(","),
    providersDown = flag(args, "down")?.split(",") ?: emptyList(),
    envKeys = flag(args, "env")?.split(",") ?: emptyList(),
    freeOnly = has(args, "free-only"),
)

/** Golden-vector conformance harness (protocol §8.3). Returns the number of failing vectors. */
private fun conformance(): Int {
    val providers = Registry.load()
    val rules = loadRules()
    var checks = 0
    var failures = 0

    fun report(suite: String, id: String, problems: List<String>) {
        checks++
        if (problems.isEmpty()) {
            println("  PASS $suite/$id")
        } else {
            failures++
            println("  FAIL $suite/$id: ${problems.joinToString("; ")}")
        }
    }

    println("routing (${providers.size} providers in registry)")
    val routing = Json.parse(Files.readString(Paths2.fixtures().resolve("routing-cases.json")))
    for (case in routing.field("cases").listOrNull() ?: emptyList()) {
        val id = case.field("id").stringOrNull() ?: "?"
        val request = case.field("request")
        val built = RouteRequest(
            capability = request.field("capability").stringOrNull(),
            prompt = request.field("prompt").stringOrNull(),
            tags = request.field("tags").stringList(),
            prefer = request.field("prefer").stringOrNull() ?: "balanced",
            providersAvailable = request.field("providers_available").stringList().ifEmpty { null },
            providersDown = request.field("providers_down").stringList(),
            envKeys = request.field("env_keys").stringList(),
            freeOnly = request.field("free_only").boolOrNull() ?: false,
        )
        val view = Router.route(providers, built).view()
        val problems = mutableListOf<String>()
        for ((key, want) in (case.field("expect") as? JsonObject)?.entries ?: emptyMap<String, JsonValue>()) {
            val got = view[key]
            if (!sameValue(got, want)) problems.add("$key: want ${want.render()} got ${valueText(got)}")
        }
        report("routing", id, problems)
    }

    println("policy")
    val policy = Json.parse(Files.readString(Paths2.fixtures().resolve("policy-cases.json")))
    for (case in policy.field("cases").listOrNull() ?: emptyList()) {
        val id = case.field("id").stringOrNull() ?: "?"
        val tool = case.field("tool").stringOrNull() ?: ""
        val args = Conversions.toMap(case.field("args"))
        val verdict = Guard.evaluate(rules, tool, args)
        val expect = case.field("expect")
        val problems = mutableListOf<String>()
        if (verdict.decision != expect.field("decision").stringOrNull()) {
            problems.add("decision: want ${expect.field("decision")} got ${verdict.decision}")
        }
        if (verdict.code != expect.field("code").stringOrNull()) {
            problems.add("code: want ${expect.field("code")} got ${verdict.code}")
        }
        report("policy", id, problems)
    }

    println("tool loop")
    val toolCases = Json.parse(Files.readString(Paths2.fixtures().resolve("tool-cases.json")))
    val ctx = ToolContext(Paths2.repoRoot(), rules, live = false)
    for (case in toolCases.field("cases").listOrNull() ?: emptyList()) {
        val id = case.field("id").stringOrNull() ?: "?"
        val outcome = Agent.runScriptedLoop(case.field("script").listOrNull() ?: emptyList(), ctx)
        val expect = case.field("expect")
        val problems = mutableListOf<String>()
        val wantTools = expect.field("tools").stringList()
        val wantResults = expect.field("results").stringList()
        val wantFinal = expect.field("final").stringOrNull() ?: ""
        if (outcome.tools != wantTools) problems.add("tools: want $wantTools got ${outcome.tools}")
        if (outcome.results != wantResults) problems.add("results: want $wantResults got ${outcome.results}")
        if (outcome.final != wantFinal) problems.add("final: want '$wantFinal' got '${outcome.final}'")
        report("tools", id, problems)
    }

    println("\nconformance (kotlin): ${checks - failures}/$checks vectors pass")
    return failures
}

private fun sameValue(got: Any?, want: JsonValue): Boolean {
    if (got == null && want is JsonNull) return true
    if (got is List<*> && want is JsonArray) {
        return got.size == want.items.size && got.indices.all { sameValue(it.let { i -> got[i] }, want.items[it]) }
    }
    if (got is String && want is JsonString) return got == want.value
    if (got is Boolean && want is JsonBool) return got == want.value
    if (got is Long && want is JsonNumber) return got.toString() == want.raw
    if (got is Int && want is JsonNumber) return got.toString() == want.raw
    return false
}

private fun valueText(value: Any?): String = if (value == null) "null" else jsonText(value)

private fun doctor(): Int {
    val providers = Registry.load()
    var reachable = 0
    val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(4)).build()
    for (provider in providers) {
        val url = if (provider.kind == "ollama-native") "${provider.baseUrl}/api/tags" else "${provider.baseUrl}/models"
        var status = "unreachable"
        try {
            val request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(4)).GET().build()
            val response = client.send(request, HttpResponse.BodyHandlers.discarding())
            status = response.statusCode().toString()
            if (response.statusCode() == 200) reachable++
        } catch (error: Exception) {
            status = "error:${error.javaClass.simpleName}"
        }
        println("${provider.id.padEnd(16)} ${provider.tier.padEnd(6)} ${status.padEnd(12)} $url")
    }
    println("\nreachable: $reachable/${providers.size}")
    return 0
}

fun main(args: Array<String>) {
    val command = args.firstOrNull() ?: "help"
    val rest = args.drop(1)
    val providers = if (command == "help") emptyList() else Registry.load()

    when (command) {
        "providers" -> providers.forEach { provider ->
            val mark = if (provider.reachable) "●" else "○"
            println("$mark ${provider.id.padEnd(16)} ${provider.tier.padEnd(6)} ${provider.priority.toString().padStart(3)} ${provider.kind.padEnd(18)} ${provider.baseUrl}")
        }
        "route" -> {
            val decision = Router.route(providers, requestFrom(rest))
            if (has(rest, "json")) {
                println(jsonText(decision.asMap(), indent = 2))
            } else {
                val fallbacks = decision.fallbacks.joinToString(", ") { it.provider }.ifEmpty { "none" }
                println("${decision.status} ${decision.routeId ?: decision.errorCode} -> ${decision.provider ?: "-"} / ${decision.model ?: "-"} (fallbacks: $fallbacks)")
            }
            if (decision.status != "ok") exitProcess(3)
        }
        "infer" -> println(Router.inferCapability(requestFrom(rest)))
        "tool" -> {
            val name = rest.firstOrNull { !it.startsWith("--") } ?: ""
            val argsJson = flag(rest, "args") ?: "{}"
            val ctx = ToolContext(Paths2.repoRoot(), loadRules(), has(rest, "live"))
            println(jsonText(Tools.runTool(name, Conversions.toMap(Json.parse(argsJson)), ctx).asMap(), indent = 2))
        }
        "loop" -> {
            val ctx = ToolContext(Paths2.repoRoot(), loadRules(), live = false)
            val script = Json.parse(flag(rest, "script") ?: "[]").listOrNull() ?: emptyList()
            val outcome = Agent.runScriptedLoop(script, ctx)
            println(jsonText(mapOf("tools" to outcome.tools, "results" to outcome.results, "final" to outcome.final), indent = 2))
        }
        "live" -> {
            val decision = Router.route(providers, requestFrom(rest))
            val apiKey = decision.authKeyEnv?.let { System.getenv(it) }
            val outcome = Agent.runLiveLoop(
                decision,
                flag(rest, "prompt") ?: "reply with exactly: ZEN_OK",
                ToolContext(Paths2.repoRoot(), loadRules(), live = true),
                apiKey,
            )
            MemoryStore(Paths2.repoRoot().resolve("memory").resolve("memory.jsonl")).append(
                mapOf("kind" to "answer", "route" to decision.routeId, "tools" to outcome.tools, "final" to outcome.final),
            )
            println(jsonText(mapOf(
                "route" to decision.routeId, "provider" to decision.provider, "model" to decision.model,
                "tools" to outcome.tools, "results" to outcome.results, "final" to outcome.final,
            ), indent = 2))
        }
        "mcp" -> {
            // auto-detect the transport: an http(s) target speaks HTTP MCP
            val target = rest.firstOrNull { !it.startsWith("--") } ?: ""
            if (target.isEmpty()) {
                println("usage: zen-agent mcp http://127.0.0.1:8802/mcp [--call tool --args json]")
            } else if (!target.startsWith("http")) {
                println("this head speaks HTTP MCP only; use the node or python head for stdio servers")
            } else {
                val client = McpHttpClient(target).start()
                val tool = flag(rest, "call")
                if (tool != null && tool.isNotEmpty()) {
                    val args = Conversions.toMap(Json.parse(flag(rest, "args") ?: "{}"))
                    println(jsonText(Conversions.toAny(client.callTool(tool, args)), indent = 2))
                } else {
                    val tools = client.listTools()
                    tools.forEach { (name, description) -> println("${name.padEnd(28)} ${description.take(90)}") }
                    println("\n${tools.size} tools from $target")
                }
            }
        }
        "memory" -> {
            val hits = MemoryStore(Paths2.repoRoot().resolve("memory").resolve("memory.jsonl")).recall(flag(rest, "query") ?: "")
            println(jsonText(hits.map { it.render() }, indent = 2))
        }
        "conformance" -> if (conformance() != 0) exitProcess(1)
        "doctor" -> exitProcess(doctor())
        "selftest" -> {
            val decision = Router.route(providers, RouteRequest(capability = "code", prefer = "local"))
            println("registry: ${providers.size} providers")
            println("route:    ${decision.routeId} -> ${decision.model} @ ${decision.endpoint}")
            println("kotlin:   ${KotlinVersion.CURRENT}")
            println("jvm:      ${System.getProperty("java.version")}")
            println("root:     ${Paths2.repoRoot()}")
        }
        else -> println(
            """
            zen-agent (kotlin head) — usage
              selftest | providers | route --capability code [--prefer local] [--json]
              infer --prompt "..." | tool calc --args '{"expression":"6*7"}' [--live]
              loop --script '[...]' | live --prompt '...' | memory --query "..."
              conformance | doctor
            """.trimIndent(),
        )
    }
}

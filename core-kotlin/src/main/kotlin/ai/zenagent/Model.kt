package ai.zenagent

import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths

/** Protocol v1 model — mirrors providers/providers.json exactly. */
data class ProviderAuth(
    val style: String,
    val keyRequired: Boolean,
    val keyEnv: String?,
) {
    companion object {
        fun from(node: JsonValue?): ProviderAuth = ProviderAuth(
            style = node.field("style").stringOrNull() ?: "none",
            keyRequired = node.field("key_required").boolOrNull() ?: false,
            keyEnv = node.field("key_env").stringOrNull(),
        )
    }
}

data class Provider(
    val id: String,
    val label: String,
    val kind: String,
    val baseUrl: String,
    val auth: ProviderAuth,
    val tier: String,
    val priority: Int,
    val reachable: Boolean,
    val models: Map<String, String>,
) {
    companion object {
        fun from(node: JsonValue): Provider = Provider(
            id = node.field("id").stringOrNull() ?: error("provider without id"),
            label = node.field("label").stringOrNull() ?: "",
            kind = node.field("kind").stringOrNull() ?: "openai-compatible",
            baseUrl = node.field("base_url").stringOrNull() ?: "",
            auth = ProviderAuth.from(node.field("auth")),
            tier = node.field("tier").stringOrNull() ?: "unknown",
            priority = node.field("priority")?.let { (it as? JsonNumber)?.asLong?.toInt() } ?: 100,
            reachable = node.field("verified").field("reachable").boolOrNull() ?: false,
            models = (node.field("models") as? JsonObject)?.entries?.mapValues { it.value.stringOrNull() ?: "" } ?: emptyMap(),
        )
    }
}

data class RouteRequest(
    val capability: String? = null,
    val tags: List<String> = emptyList(),
    val prompt: String? = null,
    val prefer: String = "balanced",
    val providersAvailable: List<String>? = null,
    val providersDown: List<String> = emptyList(),
    val envKeys: List<String> = emptyList(),
    val freeOnly: Boolean = false,
)

data class Fallback(val provider: String, val model: String)

data class RouteDecision(
    val status: String,
    val routeId: String?,
    val capability: String,
    val provider: String?,
    val model: String?,
    val endpoint: String?,
    val kind: String?,
    val tier: String?,
    val authStyle: String?,
    val authKeyEnv: String?,
    val keyRequired: Boolean?,
    val prefer: String,
    val fallbacks: List<Fallback>,
    val reason: String?,
    val errorCode: String?,
) {
    /** The exact projection every runtime must agree on. */
    fun view(): Map<String, Any?> = mapOf(
        "status" to status,
        "route_id" to routeId,
        "capability" to capability,
        "provider" to provider,
        "model" to model,
        "tier" to tier,
        "auth_style" to authStyle,
        "key_required" to keyRequired,
        "fallback_providers" to fallbacks.map { it.provider },
        "error_code" to errorCode,
    )

    fun asMap(): Map<String, Any?> = mapOf(
        "status" to status,
        "route_id" to routeId,
        "capability" to capability,
        "provider" to provider,
        "model" to model,
        "endpoint" to endpoint,
        "kind" to kind,
        "tier" to tier,
        "auth_style" to authStyle,
        "auth_key_env" to authKeyEnv,
        "key_required" to keyRequired,
        "prefer" to prefer,
        "fallbacks" to fallbacks.map { mapOf("provider" to it.provider, "model" to it.model) },
        "reason" to reason,
        "error_code" to errorCode,
    )
}

data class PolicyRules(
    val enabledTools: List<String>,
    val writeRoots: List<String>,
    val networkAllow: List<String>,
    val maxCalcOps: Int,
    val denyArgPatterns: List<String>,
) {
    companion object {
        fun from(node: JsonValue): PolicyRules = PolicyRules(
            enabledTools = node.field("enabled_tools").stringList(),
            writeRoots = node.field("write_roots").stringList(),
            networkAllow = node.field("network_allow").stringList(),
            maxCalcOps = node.field("max_calc_ops")?.let { (it as? JsonNumber)?.asLong?.toInt() } ?: 512,
            denyArgPatterns = node.field("deny_arg_patterns").stringList(),
        )
    }
}

data class Verdict(val decision: String, val code: String)

data class ToolResult(
    val tool: String,
    val ok: Boolean,
    val result: String,
    val decision: String,
    val code: String,
) {
    fun asMap(): Map<String, Any?> = mapOf(
        "tool" to tool, "ok" to ok, "result" to result, "decision" to decision, "code" to code,
    )
}

data class LoopOutcome(val tools: List<String>, val results: List<String>, val final: String)

data class ToolContext(val root: Path, val rules: PolicyRules, val live: Boolean)

/** Repo root: explicit env/property wins, otherwise walk up looking for the registry. */
object Paths2 {
    fun repoRoot(): Path {
        System.getenv("ZEN_AGENT_ROOT")?.let { if (it.isNotBlank()) return Paths.get(it).toAbsolutePath() }
        System.getProperty("ZEN_AGENT_ROOT")?.let { if (it.isNotBlank()) return Paths.get(it).toAbsolutePath() }
        var candidate: Path? = Paths.get("").toAbsolutePath()
        while (candidate != null) {
            if (Files.exists(candidate.resolve("providers").resolve("providers.json"))) return candidate
            candidate = candidate.parent
        }
        return Paths.get("").toAbsolutePath()
    }

    fun registryPath(): Path = repoRoot().resolve("providers").resolve("providers.json")
    fun fixtures(): Path = repoRoot().resolve("protocol").resolve("fixtures")
}

package ai.zenagent

import java.nio.file.Files
import java.nio.file.Path

object Registry {
    fun load(path: Path = Paths2.registryPath()): List<Provider> {
        val root = Json.parse(Files.readString(path))
        val providers = root.field("providers").listOrNull()?.map { Provider.from(it) } ?: emptyList()
        require(providers.isNotEmpty()) { "registry $path has no providers" }
        return providers
    }
}

/** Provider registry + deterministic routing, protocol §2 and §3. */
object Router {
    private val tierRank = mapOf("local" to 0, "free" to 1, "paid" to 2)

    /** Capability inference: first match wins; the order is part of the protocol. */
    private val capabilityTable: List<Pair<String, Regex>> = listOf(
        "voice" to Regex("\\b(?:voice|speak|audio|tts|transcribe)\\b"),
        "vision" to Regex("\\b(?:image|screenshot|photo|vision|ocr)\\b"),
        "math" to Regex("\\b(?:math|calcul\\w*|arithmetic|integral|equation|solve)\\b"),
        "long" to Regex("\\b(?:summar\\w*|digest|document|pdf|translat\\w*|long-context)\\b"),
        "code" to Regex("\\b(?:code|refactor|debug|compile|typescript|kotlin|python|java|script|api|endpoint)\\b"),
        "reason" to Regex("\\b(?:reason\\w*|plan|analy\\w*|strategy|proof|why)\\b"),
    )

    fun inferCapability(request: RouteRequest): String {
        request.capability?.let { return it }
        val haystack = (request.tags + listOfNotNull(request.prompt)).joinToString(" ").lowercase()
        for ((capability, pattern) in capabilityTable) if (pattern.containsMatchIn(haystack)) return capability
        return "chat"
    }

    /** A provider that needs a key it has not been given is not a candidate. */
    fun eligible(provider: Provider, request: RouteRequest, capability: String): Boolean {
        request.providersAvailable?.let { if (provider.id !in it) return false }
        if (provider.id in request.providersDown) return false
        if (!provider.models.containsKey(capability)) return false
        if (provider.auth.keyRequired && provider.auth.keyEnv !in request.envKeys) return false
        if (request.freeOnly && provider.auth.keyRequired) return false
        return true
    }

    private fun rank(provider: Provider): Int = tierRank[provider.tier] ?: 3

    private fun sortKey(prefer: String, provider: Provider): List<Any> = when (prefer) {
        "local" -> listOf(if (provider.tier == "local") 0 else 1, provider.priority, provider.id)
        "quality" -> listOf(provider.priority, rank(provider), provider.id)
        else -> listOf(rank(provider), provider.priority, provider.id)
    }

    private fun compareKeys(a: List<Any>, b: List<Any>): Int {
        for (i in a.indices) {
            val x = a[i]
            val y = b[i]
            val result = if (x is Int && y is Int) x.compareTo(y) else x.toString().compareTo(y.toString())
            if (result != 0) return result
        }
        return 0
    }

    fun route(providers: List<Provider>, request: RouteRequest): RouteDecision {
        val capability = inferCapability(request)
        val prefer = request.prefer.ifBlank { "balanced" }
        val candidates = providers.filter { eligible(it, request, capability) }

        if (candidates.isEmpty()) {
            return RouteDecision(
                status = "error", routeId = null, capability = capability, provider = null, model = null,
                endpoint = null, kind = null, tier = null, authStyle = null, authKeyEnv = null,
                keyRequired = null, prefer = prefer, fallbacks = emptyList(),
                reason = "no candidate survived the filter set",
                errorCode = "no_provider_for_capability",
            )
        }

        val ordered = candidates.sortedWith { a, b -> compareKeys(sortKey(prefer, a), sortKey(prefer, b)) }
        val chosen = ordered.first()
        val fallbacks = ordered.drop(1).take(3).map { Fallback(it.id, it.models[capability] ?: "") }
        val keyRequired = chosen.auth.keyRequired

        return RouteDecision(
            status = "ok",
            routeId = "rt-$capability-${chosen.id}",
            capability = capability,
            provider = chosen.id,
            model = chosen.models[capability],
            endpoint = chosen.baseUrl,
            kind = chosen.kind,
            tier = chosen.tier,
            authStyle = if (keyRequired) chosen.auth.style else "none",
            authKeyEnv = if (keyRequired) chosen.auth.keyEnv else null,
            keyRequired = keyRequired,
            prefer = prefer,
            fallbacks = fallbacks,
            reason = "tier=${chosen.tier} priority=${chosen.priority} candidates=${candidates.size} prefer=$prefer",
            errorCode = null,
        )
    }
}

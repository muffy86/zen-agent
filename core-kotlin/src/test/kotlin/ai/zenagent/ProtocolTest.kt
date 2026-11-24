package ai.zenagent

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * The same golden vectors the TypeScript and Python heads are held to.
 * Expected values are compared as canonical JSON text, so a Kotlin Long and a JsonNumber
 * for 108 are the same answer, and a missing field is a visible mismatch rather than a pass.
 */
class ProtocolTest {

    private val providers = Registry.load()
    private val rules = PolicyRules.from(
        Json.parse(Files.readString(Paths2.fixtures().resolve("policy-cases.json"))).field("rules")
            ?: error("policy fixture has no 'rules' block"),
    )

    private fun fixtures(name: String): JsonValue =
        Json.parse(Files.readString(Paths2.fixtures().resolve(name)))

    private fun assertSameJson(message: String, expected: JsonValue?, actual: Any?) {
        assertEquals(expected?.render() ?: "null", jsonText(actual), message)
    }

    @Test
    fun `routing vectors`() {
        val cases = fixtures("routing-cases.json").field("cases").listOrNull() ?: emptyList()
        assertTrue(cases.size >= 15, "routing vectors must not shrink")
        for (case in cases) {
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
            for ((key, want) in (case.field("expect") as? JsonObject)?.entries ?: emptyMap<String, JsonValue>()) {
                assertSameJson("$id field=$key", want, view[key])
            }
        }
    }

    @Test
    fun `policy vectors`() {
        val cases = fixtures("policy-cases.json").field("cases").listOrNull() ?: emptyList()
        assertTrue(cases.size >= 12, "policy vectors must not shrink")
        for (case in cases) {
            val id = case.field("id").stringOrNull() ?: "?"
            val verdict = Guard.evaluate(
                rules,
                case.field("tool").stringOrNull() ?: "",
                Conversions.toMap(case.field("args")),
            )
            assertEquals(case.field("expect").field("decision").stringOrNull(), verdict.decision, "$id decision")
            assertEquals(case.field("expect").field("code").stringOrNull(), verdict.code, "$id code")
        }
    }

    @Test
    fun `tool loop vectors`() {
        val cases = fixtures("tool-cases.json").field("cases").listOrNull() ?: emptyList()
        assertTrue(cases.size >= 5, "tool vectors must not shrink")
        val ctx = ToolContext(Paths2.repoRoot(), rules, live = false)
        for (case in cases) {
            val id = case.field("id").stringOrNull() ?: "?"
            val outcome = Agent.runScriptedLoop(case.field("script").listOrNull() ?: emptyList(), ctx)
            assertSameJson("$id tools", case.field("expect").field("tools"), outcome.tools)
            assertSameJson("$id results", case.field("expect").field("results"), outcome.results)
            assertEquals(case.field("expect").field("final").stringOrNull(), outcome.final, "$id final")
        }
    }

    @Test
    fun `calculator truncates toward zero`() {
        assertEquals(42L, Calculator.calc("6*7"))
        assertEquals(20L, Calculator.calc("(2+3)*4"))
        assertEquals(-2L, Calculator.calc("-5 + (10/3)"), "truncation, not flooring")
        assertFailsWith<Calculator.CalcError> { Calculator.calc("1/0") }
    }

    @Test
    fun `capability inference order`() {
        assertEquals("voice", Router.inferCapability(RouteRequest(prompt = "transcribe this audio")))
        assertEquals("vision", Router.inferCapability(RouteRequest(prompt = "read this screenshot")))
        assertEquals("math", Router.inferCapability(RouteRequest(tags = listOf("solve the integral"))))
        assertEquals("long", Router.inferCapability(RouteRequest(prompt = "summarize the pdf")))
        assertEquals("code", Router.inferCapability(RouteRequest(tags = listOf("refactor kotlin"))))
        assertEquals("reason", Router.inferCapability(RouteRequest(prompt = "plan the strategy")))
        assertEquals("chat", Router.inferCapability(RouteRequest(prompt = "hello there")))
    }

    @Test
    fun `unknown provider is an error not a guess`() {
        val decision = Router.route(providers, RouteRequest(capability = "chat", providersAvailable = listOf("does-not-exist")))
        assertEquals("error", decision.status)
        assertEquals("no_provider_for_capability", decision.errorCode)
    }

    @Test
    fun `json round trip`() {
        val sample = """{"a":[1,2,{"b":"\u00e9\n"}],"c":true,"d":null}"""
        val parsed = Json.parse(sample)
        assertEquals("é\n", parsed.field("a").listOrNull()!![2].field("b").stringOrNull())
        assertSameJson("round trip", parsed, Conversions.toAny(parsed))
    }
}

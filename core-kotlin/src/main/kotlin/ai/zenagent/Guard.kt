package ai.zenagent

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import java.time.Duration

/** The policy gate (protocol §5). Runs BEFORE any tool, in every mode. */
object Guard {

    class WritePath(val decision: String, val code: String, val path: String?)

    fun checkWritePath(raw: String, roots: List<String>): WritePath {
        if (raw.startsWith("/")) return WritePath("deny", "path_outside_write_root", null)
        val out = mutableListOf<String>()
        for (segment in raw.split("/")) {
            if (segment.isEmpty() || segment == ".") continue
            if (segment == "..") {
                // popping past the first segment means the caller tried to leave the sandbox
                if (out.size <= 1) return WritePath("deny", "path_traversal", null)
                out.removeAt(out.size - 1)
                continue
            }
            out.add(segment)
        }
        if (out.isEmpty() || out.first() !in roots) return WritePath("deny", "path_outside_write_root", null)
        return WritePath("allow", "ok", out.joinToString("/"))
    }

    /** Pure normalisation of a relative read path (no root confinement, only traversal safety). */
    fun normalizeRel(raw: String): String {
        val out = mutableListOf<String>()
        for (segment in raw.split("/")) {
            if (segment.isEmpty() || segment == ".") continue
            if (segment == "..") { if (out.isNotEmpty()) out.removeAt(out.size - 1); continue }
            out.add(segment)
        }
        return out.joinToString("/")
    }

    fun evaluate(rules: PolicyRules, tool: String, args: Map<String, Any?>): Verdict {
        // 1. only tools on the list exist at all — shell.exec is absent on purpose
        if (tool !in rules.enabledTools) return Verdict("deny", "tool_not_enabled")

        // 2. prompt-injection hygiene: arguments are data, never instructions
        val haystack = jsonText(args).lowercase()
        for (pattern in rules.denyArgPatterns) {
            if (haystack.contains(pattern.lowercase())) return Verdict("deny", "injection_suspected")
        }

        // 3. filesystem writes stay inside a root, with no traversal
        if (tool == "fs.write") {
            val verdict = checkWritePath(args["path"] as? String ?: "", rules.writeRoots)
            if (verdict.decision == "deny") return Verdict(verdict.decision, verdict.code)
        }

        // reads are not confined to write roots, but must not climb out of the project
        if (tool == "fs.read") {
            val raw = args["path"] as? String ?: ""
            if (raw.startsWith("/")) return Verdict("deny", "path_outside_write_root")
            var depth = 0
            for (segment in raw.split("/")) {
                if (segment.isEmpty() || segment == ".") continue
                if (segment == "..") {
                    if (depth == 0) return Verdict("deny", "path_traversal")
                    depth--
                    continue
                }
                depth++
            }
        }

        // 4. network egress is an allow-list of origins
        if (tool == "net.get") {
            val url = args["url"] as? String ?: ""
            if (rules.networkAllow.none { url.startsWith(it) }) return Verdict("deny", "host_not_allowed")
        }

        // 5. cheap guard against unbounded work
        if (tool == "calc") {
            val expression = args["expression"] as? String ?: ""
            if (expression.length > rules.maxCalcOps) return Verdict("deny", "expression_too_large")
        }

        return Verdict("allow", "ok")
    }
}

/** Integer arithmetic: + - * / and parentheses. Division truncates toward zero. */
object Calculator {
    class CalcError(message: String) : RuntimeException(message)

    private class Parser(private val source: String) {
        private var position = 0

        fun peek(): Char? = if (position < source.length) source[position] else null

        fun parse(): Long {
            val value = expr()
            if (position != source.length) throw CalcError("trailing_input_at_$position")
            return value
        }

        fun expr(): Long {
            var value = term()
            while (peek() == '+' || peek() == '-') {
                val op = source[position++]
                val rhs = term()
                value = if (op == '+') value + rhs else value - rhs
            }
            return value
        }

        fun term(): Long {
            var value = factor()
            while (peek() == '*' || peek() == '/') {
                val op = source[position++]
                val rhs = factor()
                value = if (op == '*') value * rhs else {
                    if (rhs == 0L) throw CalcError("division_by_zero")
                    value / rhs // Kotlin Long division truncates toward zero
                }
            }
            return value
        }

        fun factor(): Long {
            if (peek() == '-') { position++; return -factor() }
            if (peek() == '(') {
                position++
                val value = expr()
                if (peek() != ')') throw CalcError("unbalanced_parenthesis")
                position++
                return value
            }
            val start = position
            while (position < source.length && source[position].isDigit()) position++
            if (position == start) throw CalcError("not_a_number_at_$start")
            return source.substring(start, position).toLong()
        }
    }

    fun calc(expression: String): Long = Parser(expression.filterNot { it.isWhitespace() }).parse()
}

/** Tools (protocol §6): every call goes through the gate first. */
object Tools {

    fun runTool(name: String, args: Map<String, Any?>, ctx: ToolContext): ToolResult {
        val verdict = Guard.evaluate(ctx.rules, name, args)
        if (verdict.decision == "deny") {
            return ToolResult(name, false, "DENIED:${verdict.code}", "deny", verdict.code)
        }
        return try {
            when (name) {
                "calc" -> ok(name, Calculator.calc(args["expression"] as? String ?: "").toString(), verdict.code)
                "fs.read" -> {
                    val rel = Guard.normalizeRel(args["path"] as? String ?: "")
                    val body = Files.readString(ctx.root.resolve(rel)).trimEnd()
                    ok(name, body, verdict.code)
                }
                "fs.write" -> {
                    val rel = Guard.checkWritePath(args["path"] as? String ?: "", ctx.rules.writeRoots).path ?: ""
                    val target: Path = ctx.root.resolve(rel)
                    target.parent?.let { Files.createDirectories(it) }
                    Files.writeString(target, args["content"] as? String ?: "")
                    ok(name, "ok:$rel", verdict.code)
                }
                "text.echo" -> ok(name, args["text"] as? String ?: "", verdict.code)
                "net.get" -> {
                    val url = args["url"] as? String ?: ""
                    if (!ctx.live) ok(name, "STUB:no-network-in-fixture-mode", verdict.code)
                    else {
                        val request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(30)).GET().build()
                        val response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString())
                        ok(name, "${response.statusCode()} ${response.body().take(256)}", verdict.code)
                    }
                }
                else -> ToolResult(name, false, "ERROR:unknown_tool:$name", "allow", "unknown_tool")
            }
        } catch (error: Exception) {
            ToolResult(name, false, "ERROR:${error.message}", "allow", "tool_error")
        }
    }

    private fun ok(tool: String, result: String, code: String) = ToolResult(tool, true, result, "allow", code)

    val schema: List<Map<String, Any?>> = listOf(
        mapOf(
            "type" to "function",
            "function" to mapOf(
                "name" to "calc", "description" to "Integer arithmetic: + - * / and parentheses.",
                "parameters" to mapOf("type" to "object", "properties" to mapOf("expression" to mapOf("type" to "string")), "required" to listOf("expression")),
            ),
        ),
        mapOf(
            "type" to "function",
            "function" to mapOf(
                "name" to "fs.read", "description" to "Read a file inside the sandbox root.",
                "parameters" to mapOf("type" to "object", "properties" to mapOf("path" to mapOf("type" to "string")), "required" to listOf("path")),
            ),
        ),
        mapOf(
            "type" to "function",
            "function" to mapOf(
                "name" to "fs.write", "description" to "Write a file inside a configured write root.",
                "parameters" to mapOf(
                    "type" to "object",
                    "properties" to mapOf("path" to mapOf("type" to "string"), "content" to mapOf("type" to "string")),
                    "required" to listOf("path", "content"),
                ),
            ),
        ),
    )
}

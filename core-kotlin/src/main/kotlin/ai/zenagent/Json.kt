package ai.zenagent

/**
 * Minimal dependency-free JSON. The runtime must build and run as a single fat jar with nothing
 * but kotlin-stdlib on the classpath, so the protocol's own parser lives here rather than a library.
 */
sealed interface JsonValue {
    fun write(sb: StringBuilder, indent: Int, depth: Int)
    /** Canonical, compact form. Named `render` rather than `toString` on purpose: an interface may not override Any. */
    fun render(): String = StringBuilder().also { write(it, 0, 0) }.toString()
}

data class JsonObject(val entries: LinkedHashMap<String, JsonValue>) : JsonValue {
    override fun write(sb: StringBuilder, indent: Int, depth: Int) {
        if (entries.isEmpty()) { sb.append("{}"); return }
        sb.append('{')
        var first = true
        for ((key, value) in entries) {
            if (!first) sb.append(',')
            first = false
            if (indent > 0) sb.append('\n').append(" ".repeat(indent * (depth + 1)))
            sb.append('"').append(Json.escape(key)).append('"').append(':')
            if (indent > 0) sb.append(' ')
            value.write(sb, indent, depth + 1)
        }
        if (indent > 0) sb.append('\n').append(" ".repeat(indent * depth))
        sb.append('}')
    }
}

data class JsonArray(val items: List<JsonValue>) : JsonValue {
    override fun write(sb: StringBuilder, indent: Int, depth: Int) {
        if (items.isEmpty()) { sb.append("[]"); return }
        sb.append('[')
        items.forEachIndexed { index, value ->
            if (index > 0) sb.append(',')
            if (indent > 0) sb.append('\n').append(" ".repeat(indent * (depth + 1)))
            value.write(sb, indent, depth + 1)
        }
        if (indent > 0) sb.append('\n').append(" ".repeat(indent * depth))
        sb.append(']')
    }
}

data class JsonString(val value: String) : JsonValue {
    override fun write(sb: StringBuilder, indent: Int, depth: Int) { sb.append('"').append(Json.escape(value)).append('"') }
}

data class JsonNumber(val raw: String) : JsonValue {
    val asLong: Long get() = raw.substringBefore('.').toLong()
    val asDouble: Double get() = raw.toDouble()
    override fun write(sb: StringBuilder, indent: Int, depth: Int) { sb.append(raw) }
}

data class JsonBool(val value: Boolean) : JsonValue {
    override fun write(sb: StringBuilder, indent: Int, depth: Int) { sb.append(value) }
}

object JsonNull : JsonValue {
    override fun write(sb: StringBuilder, indent: Int, depth: Int) { sb.append("null") }
}

object Json {
    fun parse(text: String): JsonValue {
        val parser = Parser(text)
        val value = parser.value()
        parser.skipWhitespace()
        require(parser.atEnd()) { "trailing input at ${parser.position}" }
        return value
    }

    fun escape(text: String): String {
        val sb = StringBuilder()
        for (ch in text) when (ch) {
            '"' -> sb.append("\\\"")
            '\\' -> sb.append("\\\\")
            '\n' -> sb.append("\\n")
            '\r' -> sb.append("\\r")
            '\t' -> sb.append("\\t")
            else -> if (ch < ' ') sb.append("\\u%04x".format(ch.code)) else sb.append(ch)
        }
        return sb.toString()
    }

    private class Parser(private val text: String) {
        var position = 0
        fun atEnd(): Boolean = position >= text.length
        fun skipWhitespace() { while (position < text.length && text[position].isWhitespace()) position++ }

        fun value(): JsonValue {
            skipWhitespace()
            require(position < text.length) { "unexpected end of json" }
            return when (val ch = text[position]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> JsonString(string())
                't' -> { expect("true"); JsonBool(true) }
                'f' -> { expect("false"); JsonBool(false) }
                'n' -> { expect("null"); JsonNull }
                else -> if (ch == '-' || ch.isDigit()) number() else error("unexpected character '$ch' at $position")
            }
        }

        private fun expect(literal: String) {
            require(text.startsWith(literal, position)) { "expected '$literal' at $position" }
            position += literal.length
        }

        private fun obj(): JsonObject {
            position++ // {
            val entries = LinkedHashMap<String, JsonValue>()
            skipWhitespace()
            if (!atEnd() && text[position] == '}') { position++; return JsonObject(entries) }
            while (true) {
                skipWhitespace()
                val key = string()
                skipWhitespace()
                require(!atEnd() && text[position] == ':') { "expected ':' at $position" }
                position++
                entries[key] = value()
                skipWhitespace()
                require(!atEnd()) { "unterminated object" }
                when (text[position]) {
                    ',' -> position++
                    '}' -> { position++; return JsonObject(entries) }
                    else -> error("expected ',' or '}' at $position")
                }
            }
        }

        private fun arr(): JsonArray {
            position++ // [
            val items = mutableListOf<JsonValue>()
            skipWhitespace()
            if (!atEnd() && text[position] == ']') { position++; return JsonArray(items) }
            while (true) {
                items.add(value())
                skipWhitespace()
                require(!atEnd()) { "unterminated array" }
                when (text[position]) {
                    ',' -> position++
                    ']' -> { position++; return JsonArray(items) }
                    else -> error("expected ',' or ']' at $position")
                }
            }
        }

        private fun string(): String {
            require(text[position] == '"') { "expected '\"' at $position" }
            position++
            val sb = StringBuilder()
            while (true) {
                require(!atEnd()) { "unterminated string" }
                when (val ch = text[position++]) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        when (val esc = text[position++]) {
                            '"' -> sb.append('"')
                            '\\' -> sb.append('\\')
                            '/' -> sb.append('/')
                            'b' -> sb.append('\b')
                            'f' -> sb.append('\u000c')
                            'n' -> sb.append('\n')
                            'r' -> sb.append('\r')
                            't' -> sb.append('\t')
                            'u' -> { sb.append(text.substring(position, position + 4).toInt(16).toChar()); position += 4 }
                            else -> error("bad escape '\\$esc'")
                        }
                    }
                    else -> sb.append(ch)
                }
            }
        }

        private fun number(): JsonNumber {
            val start = position
            if (text[position] == '-') position++
            while (position < text.length && (text[position].isDigit() || text[position] in ".eE+-")) position++
            return JsonNumber(text.substring(start, position))
        }
    }
}

// ---- ergonomic accessors -------------------------------------------------------------

fun JsonValue?.field(name: String): JsonValue? = (this as? JsonObject)?.entries?.get(name)
fun JsonValue?.stringOrNull(): String? = (this as? JsonString)?.value
fun JsonValue?.boolOrNull(): Boolean? = (this as? JsonBool)?.value
fun JsonValue?.listOrNull(): List<JsonValue>? = (this as? JsonArray)?.items
fun JsonValue?.stringList(): List<String> = listOrNull()?.mapNotNull { it.stringOrNull() } ?: emptyList()

fun jsonObjectOf(vararg pairs: Pair<String, JsonValue?>): JsonObject =
    JsonObject(LinkedHashMap<String, JsonValue>().apply { pairs.forEach { (k, v) -> if (v != null) put(k, v) } })

fun jsonArrayOf(values: List<JsonValue>): JsonArray = JsonArray(values)

fun toJson(value: Any?): JsonValue = when (value) {
    null -> JsonNull
    is JsonValue -> value
    is String -> JsonString(value)
    is Boolean -> JsonBool(value)
    is Int -> JsonNumber(value.toString())
    is Long -> JsonNumber(value.toString())
    is Double -> JsonNumber(value.toString())
    is Map<*, *> -> JsonObject(LinkedHashMap<String, JsonValue>().apply {
        value.forEach { (k, v) -> put(k.toString(), toJson(v)) }
    })
    is List<*> -> JsonArray(value.map { toJson(it) })
    else -> JsonString(value.toString())
}

fun jsonText(value: Any?, indent: Int = 0): String {
    val node = toJson(value)
    return if (indent == 0) node.render()
    else StringBuilder().also { sb -> node.write(sb, indent, 0) }.toString()
}

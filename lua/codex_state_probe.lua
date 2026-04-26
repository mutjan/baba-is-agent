-- Minimal canary for Codex-controlled Baba Is You sessions.
--
-- codex-baba-state-probe-v1
--
-- This file intentionally does not inspect units, rules, or mmf objects. It
-- only proves that Baba loaded a Data/Lua file, called a mod hook, and allowed
-- MF_store to write to the current world's world_data.txt.

local CODEX_PROBE_MARKER = "codex-baba-state-probe-v1"

CodexStateProbe = CodexStateProbe or {}
CodexStateProbe.sequence = CodexStateProbe.sequence or 0

local function store_probe(source)
	if type(MF_store) ~= "function" then
		return
	end

	CodexStateProbe.sequence = CodexStateProbe.sequence + 1
	MF_store("world", "codex_probe", "schema", CODEX_PROBE_MARKER)
	MF_store("world", "codex_probe", "source", tostring(source or "unknown"))
	MF_store("world", "codex_probe", "sequence", tostring(CodexStateProbe.sequence))
	MF_store("world", "codex_probe", "loaded", "1")

	if (generaldata ~= nil) and (WORLD ~= nil) and (CURRLEVEL ~= nil) then
		MF_store("world", "codex_probe", "world", tostring(generaldata.strings[WORLD] or ""))
		MF_store("world", "codex_probe", "level", tostring(generaldata.strings[CURRLEVEL] or ""))
	end
end

if (mod_hook_functions ~= nil) and (mod_hook_functions["level_start"] ~= nil) then
	table.insert(mod_hook_functions["level_start"], function()
		store_probe("level_start")
	end)
end

print("Codex state probe active")

-- Lightweight live-state exporter for Codex-controlled Baba Is You sessions.
--
-- Install this file into the game's Data/Lua directory. The game loads files
-- there through modsupport.lua, then these hooks write the current runtime
-- state to a local JSON file after level load, movement, rule updates, undo,
-- and win events.

local CODEX_EXPORT_MARKER = "codex-baba-state-export-v1"

local function default_export_path()
	local home = "."
	if os ~= nil and os.getenv ~= nil then
		home = os.getenv("HOME") or "."
	end
	return home .. "/Library/Application Support/Baba_Is_You/codex_state.json"
end

local export_path = CODEX_STATE_EXPORT_PATH
if (export_path == nil) or (export_path == "") then
	export_path = default_export_path()
end

CodexStateExport = CodexStateExport or {}
CodexStateExport.turn = CodexStateExport.turn or 0
CodexStateExport.sequence = CodexStateExport.sequence or 0
CodexStateExport.last_command = CodexStateExport.last_command or ""
CodexStateExport.last_player = CodexStateExport.last_player or 0

local function json_escape(value)
	local text = tostring(value or "")
	text = string.gsub(text, "\\", "\\\\")
	text = string.gsub(text, "\"", "\\\"")
	text = string.gsub(text, "\b", "\\b")
	text = string.gsub(text, "\f", "\\f")
	text = string.gsub(text, "\n", "\\n")
	text = string.gsub(text, "\r", "\\r")
	text = string.gsub(text, "\t", "\\t")
	return "\"" .. text .. "\""
end

local function is_array(value)
	local count = 0
	local max_key = 0
	for key, _ in pairs(value) do
		if type(key) ~= "number" then
			return false
		end
		if key > max_key then
			max_key = key
		end
		count = count + 1
	end
	return max_key == count
end

local function json_value(value)
	local value_type = type(value)
	if value_type == "nil" then
		return "null"
	elseif value_type == "string" then
		return json_escape(value)
	elseif value_type == "number" then
		return tostring(value)
	elseif value_type == "boolean" then
		return value and "true" or "false"
	elseif value_type == "table" then
		local parts = {}
		if is_array(value) then
			for i = 1, #value do
				table.insert(parts, json_value(value[i]))
			end
			return "[" .. table.concat(parts, ",") .. "]"
		end
		for key, item in pairs(value) do
			table.insert(parts, json_escape(key) .. ":" .. json_value(item))
		end
		table.sort(parts)
		return "{" .. table.concat(parts, ",") .. "}"
	end
	return json_escape(value)
end

local function read_string(object, index)
	if (object ~= nil) and (object.strings ~= nil) and (index ~= nil) then
		return object.strings[index] or ""
	end
	return ""
end

local function read_value(object, index)
	if (object ~= nil) and (object.values ~= nil) and (index ~= nil) then
		return object.values[index]
	end
	return nil
end

local function read_flag(object, index)
	if (object ~= nil) and (object.flags ~= nil) and (index ~= nil) then
		return object.flags[index] == true
	end
	return false
end

local function safe_unit(unitid)
	if (unitid == nil) or (mmf == nil) or (mmf.newObject == nil) then
		return nil
	end
	local ok, unit = pcall(mmf.newObject, unitid)
	if ok then
		return unit
	end
	return nil
end

local function word_from_name(name)
	if (type(name) == "string") and (string.sub(name, 1, 5) == "text_") then
		return string.sub(name, 6)
	end
	return nil
end

local function collect_units()
	local rows = {}
	if units == nil then
		return rows
	end

	for _, unitid in ipairs(units) do
		local unit = safe_unit(unitid)
		if unit ~= nil then
			local name = read_string(unit, UNITNAME)
			local unit_type = read_string(unit, UNITTYPE)
			local x = read_value(unit, XPOS)
			local y = read_value(unit, YPOS)
			local row = {
				runtime_id = unitid,
				id = read_value(unit, ID),
				name = name,
				unit_type = unit_type,
				word = word_from_name(name),
				x = x,
				y = y,
				dir = read_value(unit, DIR),
				float = read_value(unit, FLOAT),
				type = read_value(unit, TYPE),
				zlayer = read_value(unit, ZLAYER),
				dead = read_flag(unit, DEAD),
				visible = unit.visible == true,
			}
			row.sort_key = tostring(y or 0) .. ":" .. tostring(x or 0) .. ":" .. name .. ":" .. tostring(unitid)
			table.insert(rows, row)
		end
	end

	table.sort(rows, function(a, b)
		return a.sort_key < b.sort_key
	end)
	for _, row in ipairs(rows) do
		row.sort_key = nil
	end
	return rows
end

local function contains_tag(tags, needle)
	if type(tags) ~= "table" then
		return false
	end
	for _, tag in ipairs(tags) do
		if tag == needle then
			return true
		end
	end
	return false
end

local function collect_rules_from(source, visible_lookup)
	local rows = {}
	if type(source) ~= "table" then
		return rows
	end

	local seen = {}
	for _, fullrule in ipairs(source) do
		local rule = fullrule[1] or {}
		local target = rule[1]
		local verb = rule[2]
		local effect = rule[3]
		if (target ~= nil) and (verb ~= nil) and (effect ~= nil) then
			local text = tostring(target) .. " " .. tostring(verb) .. " " .. tostring(effect)
			local tags = fullrule[4] or {}
			local key = text .. "|" .. tostring(contains_tag(tags, "base"))
			if seen[key] == nil then
				seen[key] = true
				table.insert(rows, {
					text = text,
					target = target,
					verb = verb,
					effect = effect,
					base = contains_tag(tags, "base"),
					visible = visible_lookup[text] == true,
					condition_count = #(fullrule[2] or {}),
					source_id_count = #(fullrule[3] or {}),
				})
			end
		end
	end

	table.sort(rows, function(a, b)
		return a.text < b.text
	end)
	return rows
end

local function collect_rules()
	local visible_lookup = {}
	if type(visualfeatures) == "table" then
		for _, fullrule in ipairs(visualfeatures) do
			local rule = fullrule[1] or {}
			if (rule[1] ~= nil) and (rule[2] ~= nil) and (rule[3] ~= nil) then
				visible_lookup[tostring(rule[1]) .. " " .. tostring(rule[2]) .. " " .. tostring(rule[3])] = true
			end
		end
	end
	return collect_rules_from(features, visible_lookup)
end

local function collect_feature_index()
	local rows = {}
	if type(featureindex) ~= "table" then
		return rows
	end
	for name, rules in pairs(featureindex) do
		table.insert(rows, {name = name, count = #rules})
	end
	table.sort(rows, function(a, b)
		return a.name < b.name
	end)
	return rows
end

local function metadata(source)
	local now = nil
	if os ~= nil and os.time ~= nil then
		now = os.time()
	end

	return {
		schema = CODEX_EXPORT_MARKER,
		source = source,
		exported_at = now,
		turn = CodexStateExport.turn,
		sequence = CodexStateExport.sequence,
		last_command = CodexStateExport.last_command,
		last_player = CodexStateExport.last_player,
		world = read_string(generaldata, WORLD),
		level = read_string(generaldata, CURRLEVEL),
		level_name = read_string(generaldata, LEVELNAME),
		room_width = roomsizex,
		room_height = roomsizey,
		last_key = last_key,
	}
end

local function write_export(source)
	if (io == nil) or (io.open == nil) then
		print("Codex state export unavailable: Lua io.open is missing")
		return
	end

	CodexStateExport.sequence = CodexStateExport.sequence + 1
	local state = {
		meta = metadata(source),
		rules = collect_rules(),
		feature_index = collect_feature_index(),
		units = collect_units(),
	}

	local body = json_value(state) .. "\n"
	local tmp_path = export_path .. ".tmp"
	local file, err = io.open(tmp_path, "w")
	if file == nil then
		print("Codex state export failed opening " .. tmp_path .. ": " .. tostring(err))
		return
	end
	file:write(body)
	file:close()

	local ok, rename_err = os.rename(tmp_path, export_path)
	if not ok then
		os.remove(export_path)
		ok, rename_err = os.rename(tmp_path, export_path)
	end
	if not ok then
		print("Codex state export failed writing " .. export_path .. ": " .. tostring(rename_err))
	end
end

local function safe_export(source)
	local ok, err = pcall(write_export, source)
	if not ok then
		print("Codex state export error: " .. tostring(err))
	end
end

local function register_hook(name, callback)
	if (mod_hook_functions ~= nil) and (mod_hook_functions[name] ~= nil) then
		table.insert(mod_hook_functions[name], function(extra)
			local ok, err = pcall(callback, extra or {})
			if not ok then
				print("Codex state export hook error in " .. name .. ": " .. tostring(err))
			end
		end)
	end
end

register_hook("level_start", function()
	CodexStateExport.turn = 0
	CodexStateExport.last_command = "level_start"
	CodexStateExport.last_player = 0
	safe_export("level_start")
end)

register_hook("command_given", function(extra)
	CodexStateExport.turn = CodexStateExport.turn + 1
	CodexStateExport.last_command = tostring(extra[1] or "")
	CodexStateExport.last_player = tonumber(extra[2] or 0) or 0
end)

register_hook("turn_auto", function(extra)
	CodexStateExport.turn = CodexStateExport.turn + 1
	CodexStateExport.last_command = "auto:" .. tostring(extra[1] or "") .. "," .. tostring(extra[2] or "")
	CodexStateExport.last_player = 0
end)

register_hook("movement_end", function()
	safe_export("movement_end")
end)

register_hook("rule_update_after", function(extra)
	local repeated = extra[1] == true
	if not repeated then
		safe_export("rule_update_after")
	end
end)

register_hook("effect_once", function()
	safe_export("effect_once")
end)

register_hook("undoed_after", function()
	CodexStateExport.last_command = "undo"
	safe_export("undoed_after")
end)

register_hook("level_restart", function()
	CodexStateExport.last_command = "restart"
	safe_export("level_restart")
end)

register_hook("level_win_after", function()
	CodexStateExport.last_command = "win"
	safe_export("level_win_after")
end)

print("Codex state exporter active: " .. export_path)

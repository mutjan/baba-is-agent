-- Lightweight live-state exporter for Codex-controlled Baba Is You sessions.
--
-- Install this file into the game's Data/Lua directory. The game loads files
-- there through modsupport.lua, then these hooks store the current runtime
-- state in the active save file after level load, movement, rule updates,
-- undo, and win events. This avoids relying on standard Lua io/os/pcall,
-- which are not available in Baba's embedded Lua runtime.

local CODEX_EXPORT_MARKER = "codex-baba-state-export-v1"

CodexStateExport = CodexStateExport or {}
CodexStateExport.turn = CodexStateExport.turn or 0
CodexStateExport.sequence = CodexStateExport.sequence or 0
CodexStateExport.last_command = CodexStateExport.last_command or ""
CodexStateExport.last_player = CodexStateExport.last_player or 0

local function read_string(object, index)
	if (index ~= nil) and (object ~= nil) and (object.strings ~= nil) then
		return object.strings[index] or ""
	end
	return ""
end

local function read_value(object, index)
	if (index ~= nil) and (object ~= nil) and (object.values ~= nil) then
		return object.values[index]
	end
	return nil
end

local function read_flag(object, index)
	if (index ~= nil) and (object ~= nil) and (object.flags ~= nil) then
		return object.flags[index] == true
	end
	return false
end

local function safe_unit(unitref)
	if unitref == nil then
		return nil
	end
	if type(unitref) ~= "number" then
		return unitref
	end
	if (mmf == nil) or (mmf.newObject == nil) then
		return nil
	end
	return mmf.newObject(unitref)
end

local function unit_runtime_id(unit, fallback)
	if (unit ~= nil) and (unit.fixed ~= nil) then
		return unit.fixed
	end
	return fallback
end

local function unit_key(unit, fallback)
	local id = read_value(unit, ID)
	if id ~= nil then
		return "id:" .. tostring(id)
	end
	return "fixed:" .. tostring(unit_runtime_id(unit, fallback))
end

local function fixed_key(value)
	if fixed_to_str ~= nil then
		return fixed_to_str(value)
	end
	return tostring(value)
end

local function build_unitmap_lookup()
	local lookup = {}
	if (type(unitmap) ~= "table") or (roomsizex == nil) then
		return lookup
	end

	for tileid, ids in pairs(unitmap) do
		if type(ids) == "table" then
			local y = math.floor(tileid / roomsizex)
			local x = tileid - y * roomsizex
			for _, fixedid in ipairs(ids) do
				lookup[fixed_key(fixedid)] = {x = x, y = y}
			end
		end
	end
	return lookup
end

local function word_from_name(name)
	if (type(name) == "string") and (string.sub(name, 1, 5) == "text_") then
		return string.sub(name, 6)
	end
	return nil
end

local function add_unit_row(rows, seen, coord_lookup, unitref)
	local unit = safe_unit(unitref)
	if unit == nil then
		return
	end

	local key = unit_key(unit, unitref)
	if seen[key] == true then
		return
	end
	seen[key] = true

	local name = read_string(unit, UNITNAME)
	local unit_type = read_string(unit, UNITTYPE)
	local x = read_value(unit, XPOS)
	local y = read_value(unit, YPOS)
	local mapped = coord_lookup[fixed_key(unitref)] or coord_lookup[fixed_key(unit_runtime_id(unit, unitref))]
	if mapped ~= nil then
		x = x or mapped.x
		y = y or mapped.y
	end

	local row = {
		runtime_id = unit_runtime_id(unit, unitref),
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
	row.sort_key = tostring(y or 0) .. ":" .. tostring(x or 0) .. ":" .. name .. ":" .. tostring(row.id or row.runtime_id)
	table.insert(rows, row)
end

local function collect_units()
	local rows = {}
	local seen = {}
	local coord_lookup = build_unitmap_lookup()

	if type(units) == "table" then
		for _, unitref in ipairs(units) do
			add_unit_row(rows, seen, coord_lookup, unitref)
		end
	end

	if type(unitlists) == "table" then
		for _, ids in pairs(unitlists) do
			if type(ids) == "table" then
				for _, unitid in ipairs(ids) do
					add_unit_row(rows, seen, coord_lookup, unitid)
				end
			end
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
	return {
		schema = CODEX_EXPORT_MARKER,
		source = source,
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

local function export_ready()
	return (type(MF_store) == "function") and (generaldata ~= nil)
end

local function field(value)
	local text = tostring(value or "")
	text = string.gsub(text, "\\", "\\\\")
	text = string.gsub(text, "\t", "\\t")
	text = string.gsub(text, "\n", "\\n")
	text = string.gsub(text, "\r", "\\r")
	return text
end

local function join_fields(values, count)
	local parts = {}
	for index = 1, count do
		table.insert(parts, field(values[index]))
	end
	return table.concat(parts, "\t")
end

local function store_value(key, value)
	MF_store("save", "codex_state", key, tostring(value or ""))
end

local function store_rows(prefix, rows, encode_row)
	store_value(prefix .. "_count", #rows)
	for index, row in ipairs(rows) do
		store_value(prefix .. "_" .. tostring(index), encode_row(row))
	end
end

local function write_export(source)
	if not export_ready() then
		return
	end

	CodexStateExport.sequence = CodexStateExport.sequence + 1
	local meta = metadata(source)
	local rules = collect_rules()
	local units = collect_units()
	local feature_index = collect_feature_index()

	store_value("schema", CODEX_EXPORT_MARKER)
	store_value("source", meta.source)
	store_value("turn", meta.turn)
	store_value("sequence", meta.sequence)
	store_value("last_command", meta.last_command)
	store_value("last_player", meta.last_player)
	store_value("world", meta.world)
	store_value("level", meta.level)
	store_value("level_name", meta.level_name)
	store_value("room_width", meta.room_width)
	store_value("room_height", meta.room_height)
	store_value("last_key", meta.last_key)

	store_rows("rule", rules, function(rule)
		return join_fields({
			rule.text,
			rule.target,
			rule.verb,
			rule.effect,
			rule.base and 1 or 0,
			rule.visible and 1 or 0,
			rule.condition_count,
			rule.source_id_count,
		}, 8)
	end)

	store_rows("feature", feature_index, function(feature)
		return join_fields({feature.name, feature.count}, 2)
	end)

	store_rows("unit", units, function(unit)
		return join_fields({
			unit.runtime_id,
			unit.id,
			unit.name,
			unit.unit_type,
			unit.word,
			unit.x,
			unit.y,
			unit.dir,
			unit.float,
			unit.type,
			unit.zlayer,
			unit.dead and 1 or 0,
			unit.visible and 1 or 0,
		}, 13)
	end)
end

local function safe_export(source)
	write_export(source)
end

local function register_hook(name, callback)
	if (mod_hook_functions ~= nil) and (mod_hook_functions[name] ~= nil) then
		table.insert(mod_hook_functions[name], function(extra)
			callback(extra or {})
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

print("Codex state exporter active: save/codex_state")

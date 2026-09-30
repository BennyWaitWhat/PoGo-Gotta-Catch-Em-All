// master_triage_workflow.js -- Resumable, cost-efficient purpose-audit workflow
//
// WHY THIS EXISTS:
// The first 40-agent triage run (2026-05-28) cost 2.7M tokens because it sent
// ALL 4518 profiles to 40 parallel agents. deep_profile.py now assigns purposes
// roles-first, so most mons are already correct. This v2 workflow ONLY audits
// the BORDERLINE set: mons whose deterministic purpose landed in
// {RESERVE, TRADE, TRANSFER} OR whose pvp.rank is 11-50 (the "maybe PVP" zone).
// That shrinks the input from ~4500 to ~800-1200 mons and from 40 agents to 10.
//
// COST MODEL:
// Prior run: 4518 profiles x 40 agents = ~2.7M tokens
// This run:  ~1000 borderline profiles x 10 agents = ~250-400K tokens (>80% cheaper)
//
// RESUMABILITY:
// This is a Workflow script. If it fails mid-run, resume via:
//   Workflow({ scriptPath: "system/scripts/master_triage_workflow.js",
//              resumeFromRunId: "<prior-run-id>" })
// Completed agent steps are skipped; only pending/failed steps re-execute.
//
// STRUCTURED OUTPUT:
// Every audit agent returns a JSON object matching the CorrectionReport schema
// (see CORRECTION_SCHEMA below). The final merge agent collects all corrections
// into a single output matching MasterTriageResult.

export const meta = {
  name: "master-triage-v2",
  description: "Audit borderline purpose assignments from deep_profile.py (RESERVE/TRADE/TRANSFER and pvp.rank 11-50). Resumable, ~10 agents.",
  version: "2.0.0"
};

// ---------------------------------------------------------------------------
// Schema definitions (referenced in agent prompts as StructuredOutput guides)
// ---------------------------------------------------------------------------

const CORRECTION_SCHEMA = `{
  "type": "object",
  "properties": {
    "slice_id":    { "type": "string", "description": "e.g. borderline_0" },
    "reviewed":    { "type": "integer", "description": "count of profiles inspected" },
    "corrections": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "uid":    { "type": "string", "description": "uid_hex of the mon" },
          "species":{ "type": "string" },
          "from":   { "type": "string", "enum": ["RESERVE","TRADE","TRANSFER","PVP","COLLECTION","MEGA","ADVENTURE","MAX"] },
          "to":     { "type": "string", "enum": ["PVP","COLLECTION","MEGA","ADVENTURE","MAX","RESERVE","TRADE","TRANSFER"] },
          "reason": { "type": "string", "description": "one-line justification" }
        },
        "required": ["uid","species","from","to","reason"]
      }
    },
    "anomalies": {
      "type": "array",
      "items": { "type": "string" },
      "description": "free-text notes on data oddities (missing moves, impossible IVs, etc.)"
    }
  },
  "required": ["slice_id","reviewed","corrections","anomalies"]
}`;

const MASTER_RESULT_SCHEMA = `{
  "type": "object",
  "properties": {
    "reviewed":    { "type": "integer" },
    "corrections": { "type": "array", "items": { "$ref": "#CorrectionItem" } },
    "anomalies":   { "type": "array", "items": { "type": "string" } },
    "gems":        { "type": "array", "items": { "type": "string" }, "description": "notable finds across all slices" },
    "systems":     {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "system":  { "type": "string" },
          "dossier": { "type": "string" }
        }
      },
      "description": "10 system-level dossiers (PVP meta, mega, shadows, etc.)"
    }
  },
  "required": ["reviewed","corrections","anomalies","gems","systems"]
}`;

// ---------------------------------------------------------------------------
// Step 1: Filter agent -- reads deep_profiles.json, emits the borderline slice
// ---------------------------------------------------------------------------

const filterAgent = agent({
  name: "filter-borderline",
  model: "claude-sonnet-4-20250514",
  prompt: `You are a data-filter agent. Read the file system/analysis/deep_profiles.json.

Extract ONLY the profiles where:
  (a) purpose is one of: RESERVE, TRADE, TRANSFER
  OR
  (b) pvp is not null AND pvp.rank is between 11 and 50 (inclusive)

This is the "borderline set" -- mons whose deterministic purpose is uncertain.

Output the filtered array as a JSON array (same schema as the input profiles).
Also output a summary line: "borderline_count: <N> out of <total>".

Do NOT include mons with purpose PVP/COLLECTION/MEGA/ADVENTURE/MAX unless
they match condition (b) above (pvp.rank 11-50).

Return ONLY the JSON array. No markdown fences.`,
  tools: ["Read", "Glob"]
});

// ---------------------------------------------------------------------------
// Step 2: Slicer agent -- splits borderline set into ~10 equal slices
// ---------------------------------------------------------------------------

const slicerAgent = agent({
  name: "slice-borderline",
  model: "claude-sonnet-4-20250514",
  prompt: `You receive a JSON array of borderline pokemon profiles from the previous step.

Split them into 10 roughly-equal slices (by array index, not by species).
If fewer than 100 profiles, use fewer slices (minimum 2, ~50 per slice).

Output a JSON object: { "slices": [ { "slice_id": "borderline_0", "profiles": [...] }, ... ] }
Include every profile in exactly one slice. No duplicates, no omissions.

Return ONLY the JSON object. No markdown fences.`,
  input: filterAgent
});

// ---------------------------------------------------------------------------
// Step 3: Parallel audit agents -- one per slice
// ---------------------------------------------------------------------------

// The audit prompt is shared across all parallel agents.
const AUDIT_PROMPT = `You are a Pokemon Go collection expert auditing purpose assignments.

You will receive a slice of pokemon profiles. For each mon, evaluate whether
the assigned "purpose" field is correct given the mon's attributes.

RULES FOR PURPOSE (priority order):
1. PVP     -- pvp.rank <= 10 with meta-relevant species (score >= 80), OR rank 1
2. MEGA    -- MegaBest flag (highest CP mega-eligible of its species)
3. ADVENTURE -- AdventureEffect flag (has adventure effects remaining)
4. MAX     -- Dynamax flag
5. COLLECTION -- shiny, lucky, hundo, nundo, legendary, mythical, ultra beast,
                 paradox, costume, SHUNDO, ShinyShadow, XXL, Background,
                 BestBuddy, OnlyOne, Gigantamax
6. PVP (secondary) -- pvp.rank <= 20 with viable spread
7. RESERVE -- quality battler (ivt >= 33 or has user tags) not fitting above
8. TRADE   -- decent IV dupe (ivt >= 37) with no other role
9. TRANSFER -- everything else (junk)

KEY CORRECTIONS TO LOOK FOR:
- RESERVE that should be COLLECTION (has a collection flag the code missed)
- RESERVE that should be TRANSFER (ivt < 33, no tags, no value)
- TRADE that should be COLLECTION (shiny/lucky/costume etc.)
- TRANSFER that should be RESERVE (OnlyOne, has tags, legacy move)
- pvp.rank 11-50 mons that have value as PVP (meta species, good IVs)
- pvp.rank 11-50 mons currently marked PVP that should be RESERVE or TRADE

IMPORTANT: Only emit a correction if the purpose is WRONG. If the current
purpose is defensible, skip it. Err on the side of fewer corrections.

Output your result as JSON matching this schema:
${CORRECTION_SCHEMA}

Return ONLY the JSON object. No markdown fences.`;

// We use parallel() over 10 dynamic slices. Each agent gets one slice.
const auditAgents = parallel(
  Array.from({ length: 10 }, (_, i) =>
    agent({
      name: `audit-slice-${i}`,
      model: "claude-sonnet-4-20250514",
      prompt: `${AUDIT_PROMPT}

You are processing slice "borderline_${i}". The profiles for your slice are
provided in the input. If the input contains no slice matching your index,
return: {"slice_id":"borderline_${i}","reviewed":0,"corrections":[],"anomalies":["no data for this slice"]}`,
      input: slicerAgent
    })
  )
);

// ---------------------------------------------------------------------------
// Step 4: Merge agent -- combines all slice results + writes system dossiers
// ---------------------------------------------------------------------------

const mergeAgent = agent({
  name: "merge-corrections",
  model: "claude-sonnet-4-20250514",
  prompt: `You receive the outputs of 10 audit agents (some may have 0 results if
the borderline set was small). Merge them into a single result.

TASKS:
1. Concatenate all corrections arrays. Deduplicate by uid (keep the first).
2. Concatenate all anomalies arrays. Deduplicate exact strings.
3. Sum all reviewed counts.
4. Identify "gems": notable finds worth highlighting (rank-1 hidden in RESERVE,
   shiny-shadow marked TRANSFER, etc.). Max 20 gems.
5. Write 10 brief system dossiers (1-3 sentences each) covering these systems:
   - PVP Meta (GL), PVP Meta (UL), Mega Roster, Shadow Collection,
   - Shiny Collection, Lucky Collection, Adventure Effects, Dynamax/Gigantamax,
   - Legendary/Mythical Vault, Trade Pipeline

Output as JSON matching this schema:
${MASTER_RESULT_SCHEMA}

Return ONLY the JSON object. No markdown fences.`,
  input: auditAgents
});

export default mergeAgent;

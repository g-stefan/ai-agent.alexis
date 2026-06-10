# Agent test workspace

Exercises the system-prompt + skills loading flags.

## Layout
```
test/
├─ AGENTS.md                 # project conventions (--agent-use-agents-md)
└─ .agents/
   ├─ SYSTEM.md              # base system prompt (--agent-use-system-md)
   └─ skills/                # Agent Skills (--agent-use-skills)
      ├─ pirate-speak/SKILL.md
      ├─ weather-reporter/SKILL.md
      ├─ recipe-chef/
      │  ├─ SKILL.md
      │  └─ templates/recipe-template.md   # bundled resource
      ├─ git-helper/SKILL.md
      ├─ haiku-writer/SKILL.md
      └─ toolbox/                          # runnable scripts (--agent-use-mcp-skills)
         ├─ SKILL.md
         └─ scripts/
            ├─ date.py        # current date/time
            ├─ ascii_art.py   # text -> ASCII-art banner
            └─ calc.py        # safe math evaluator
```

## Runnable skill (toolbox)
The `toolbox` skill bundles Python scripts the model runs via the skills MCP
server's `run_skill_script` tool. Enable it with `--agent-use-mcp-skills`.

| Ask for…                          | Runs                                                          |
|-----------------------------------|--------------------------------------------------------------|
| "what's the date / time"          | `run_skill_script(skill="toolbox", name="date")`             |
| "make an ASCII banner of HELLO"   | `…name="ascii_art", arguments=["HELLO"]`                     |
| "what is 2 * (3 + 4)"             | `…name="calc", arguments=["2 * (3 + 4)"]`                    |

## Trigger words (what should pull in each skill)
| Skill            | Say something like…                          |
|------------------|----------------------------------------------|
| pirate-speak     | "ahoy", "talk like a pirate"                 |
| weather-reporter | "what's the weather", "forecast", "temperature" |
| recipe-chef      | "give me a recipe", "how do I cook…"         |
| git-helper       | "git", "commit", "create a branch"           |
| haiku-writer     | "write a haiku about…", "make it poetic"     |

## Run it
From inside this folder:
```bash
cd test
python ../alexis.py -i --ui-driver textual \
  --agent-use-system-md --agent-use-agents-md --agent-use-skills \
  --agent-use-mcp-workspace --agent-use-mcp-skills \
  --url http://127.0.0.1:8080/v1/chat/completions
```
`--agent-use-mcp-workspace` lets the model read the `SKILL.md` files on demand;
`--agent-use-mcp-skills` lets it run the `toolbox` scripts.
Then try, e.g., `write a haiku about rain` or `ahoy, who are you?` and watch
which skill the model loads (it should start the reply with `> using skill: …`).

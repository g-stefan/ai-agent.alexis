# Context Memory Map Feature

The Textual Interactive UI now includes a visual **Context Memory Map** in the statistics panel that shows token usage breakdown by category. This helps you understand how your context window is being used.

## Overview

When you specify a context limit with `--context-limit`, the Textual UI displays a detailed memory map showing:

- **Token categories** - Different colored bars for each token type
- **Usage percentages** - How much of the context each category uses
- **Visual representation** - Bar graphs using Unicode block characters
- **Remaining capacity** - Free context tokens available
- **Total usage** - Overall context usage and percentage

## Display Format

The memory map appears in the right statistics panel (if context-limit is set):

```
STATISTICS
─────────────────────
Prompt: 245
Completion: 156
Total: 401
Speed: 45.32 tok/s
MCP Calls: 2

Context Map
System ███░░░░░░░░░░░  245 ( 3.1%)
Tools  ██░░░░░░░░░░░░░  120 ( 1.5%)
User   █████████░░░░░░ 1,234 (15.6%)
Think  ████░░░░░░░░░░░  450 ( 5.7%)
Calls  ██░░░░░░░░░░░░░  89  ( 1.1%)
Free   ████████████████ 5,862 (74.0%)
Total  ▓▓▓▓▓▓▓▓░░░░░░░░ 401  (26.0%)
```

## Color Coding

Each token category has a distinct color:

| Category | Color | Meaning |
|----------|-------|---------|
| **System** | Light Red `#ffcccc` | System messages and instructions |
| **Tools** | Light Yellow `#ffff99` | Tool definitions and initialization |
| **User** | White | User input and messages |
| **Think** | Light Green `#99ff99` | Thinking/reasoning tokens (extended thinking) |
| **Calls** | Light Yellow `#ffff99` | Tool call invocations |
| **Free** | Dim gray | Remaining available context |
| **Total** | Green/Yellow/Red | Overall usage (green <80%, yellow <95%, red >95%) |

## Visual Elements

### Block Characters
The memory map uses Unicode block drawing characters for compact representation:

- `█` - Full block (filled portion)
- `░` - Light shade (empty portion)
- `▓` - Dark shade (total usage bar)

These characters provide a smooth, professional appearance and are more compact than text-based percentages.

### Bar Width
Each bar is 15 characters wide (proportional scaling):

```
System ███░░░░░░░░░░░  (3 filled, 12 empty = 20% usage)
User   █████████░░░░░░ (9 filled, 6 empty = 60% usage)
```

### Usage Indicator
The total bar uses different shading based on usage percentage:

```
< 80% usage: Green (▓▓▓)
80-95% usage: Yellow (▓▓▓)
> 95% usage: Red (▓▓▓)
```

## Usage Example

### Setup with Context Limit

```bash
# Specify context limit (e.g., 8000 tokens)
python alexis.py --interactive --context-limit 8000

# With Gemini and extended thinking
python alexis.py --interactive \
  --llm-driver gemini \
  --context-limit 32000 \
  --include-thoughts \
  --reasoning-effort high
```

### Interpreting the Memory Map

When running, you'll see the breakdown update in real-time:

**Initial state (just system message):**
```
System ██░░░░░░░░░░░░░  450  ( 5.6%)
Free   ████████████████ 7,550 (94.4%)
Total  ░░░░░░░░░░░░░░░░ 450  ( 5.6%)
```

**After user input:**
```
User   █████░░░░░░░░░░ 1,200 (15.0%)
Free   ███████████░░░░ 6,800 (85.0%)
Total  ███████░░░░░░░░ 1,650 (20.6%)
```

**With extended thinking (Gemini):**
```
System ██░░░░░░░░░░░░░  450  ( 5.6%)
User   █████░░░░░░░░░░ 1,200 (15.0%)
Think  ███░░░░░░░░░░░░  800  (10.0%)
Free   ██████████░░░░░ 5,550 (69.4%)
Total  ██████████░░░░░ 2,450 (30.6%)
```

**Near capacity (warning):**
```
System ██░░░░░░░░░░░░░  450  ( 5.6%)
User   ████████████░░░ 6,200 (77.5%)
Free   █░░░░░░░░░░░░░░ 1,350 (16.9%)
Total  ▓▓▓▓▓▓▓▓▓░░░░░░ 6,650 (83.1%)  [Yellow warning]
```

**Over capacity (critical):**
```
System ██░░░░░░░░░░░░░  450  ( 5.6%)
User   ████████████████ 7,200 (90.0%)
Free   ░░░░░░░░░░░░░░░░ 350   ( 4.4%)
Total  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░ 7,650 (95.6%)  [Red critical]
```

## Token Categories Explained

### System Tokens
Tokens used by the system message (e.g., instructions, personality, rules).

**Examples:**
- `--system prompt.md` file content
- Model system instructions
- Behavioral guidelines

### Tool Tokens
Tokens used to define available tools and their schemas (MCP tool definitions).

**Examples:**
- Tool function signatures
- Tool parameter definitions
- Tool descriptions

### User Tokens
Tokens from your input messages and conversation history.

**Examples:**
- Your prompts and questions
- Previous conversation turns
- Supplementary context provided

### Think Tokens (Thinking)
Tokens used for model reasoning and thinking processes.

**Only appears when:**
- Using models with extended thinking (e.g., Gemini with --include-thoughts)
- Running with --reasoning-effort high

**Examples:**
- Internal reasoning steps
- Problem analysis
- Thought process exploration

### Call Tokens
Tokens used for tool invocations and MCP calls.

**Examples:**
- `function_name(args)` invocations
- Tool call parameters
- MCP command syntax

### Free Tokens
Remaining available context capacity.

**Useful for:**
- Knowing how much conversation you can add
- Planning follow-up messages
- Understanding when context refresh is needed

## Practical Tips

### 1. Monitor Growing Conversations
The memory map helps you see when conversation history is consuming significant tokens:

```
User tokens growing from 2% → 25% → 50% → 75%
→ Consider starting a new session when approaching limit
```

### 2. Optimize Tool Definitions
If **Tools** category is large:
- You have many tools loaded (MCP servers)
- Consider disabling unused tools
- Use `--mcp` selectively

### 3. Understanding Thinking Overhead
Extended thinking with Gemini shows **Think** tokens:

```
Without thinking: User 80%, Think 0%
With thinking:    User 40%, Think 40%  (doubled tokens used)
```

### 4. System Prompt Impact
Check **System** category size:

```
Large system prompt: System 15%, User 60%
Minimal system:      System 2%, User 75% (more space for conversation)
```

### 5. Plan Context Usage
Before starting a conversation:

```
--context-limit 8000
  System: 400 tokens (5%)
  Tools: 200 tokens (2.5%)
  Available for conversation: 7,400 tokens (92.5%)
```

## Implementation Details

### Token Estimation

The memory map uses a rough token estimation algorithm:

```
Estimated tokens ≈ text_length / 4
```

This provides approximate token counts without needing the actual tokenizer. More accurate counts come from the LLM's actual token usage (in the Prompt/Completion fields).

### Real-Time Updates

The memory map updates after each turn:

1. You send a message
2. Model responds
3. Statistics panel refreshes
4. Memory map recalculates
5. Visual display updates

### Context Limit Handling

If context is exhausted:

```
Free tokens: 0
Total usage: 100%
Total bar: ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ (all red)
```

At this point:
- No more tokens can be added
- Previous messages may need to be removed
- Consider starting a new session

## Advanced: Custom Context Limits

Different models have different context limits:

```bash
# GPT-3.5 (4K context)
--context-limit 4096

# GPT-4 (8K context)
--context-limit 8192

# Claude-3 (100K context)
--context-limit 102400

# Gemini (1M context)
--context-limit 1000000

# Llama (model-dependent)
--context-limit 2048  # 2K model
--context-limit 4096  # 4K model
--context-limit 8192  # 8K model
```

Check your model's documentation for the exact context size.

## Troubleshooting

### Memory Map Not Showing
- **Cause**: `--context-limit` not specified
- **Solution**: Add `--context-limit 8000` (or your model's limit)

### Inaccurate Token Counts
- **Cause**: Estimation algorithm is approximate
- **Solution**: Actual token counts from model are more accurate (Prompt/Completion fields)

### Memory Map Disappears
- **Cause**: Terminal too small or UI refresh issue
- **Solution**: Resize terminal or use `--ui-driver simple`

## Color Issues (Windows Terminal)

If colors don't display correctly:

```bash
# Force color mode
FORCE_COLOR=1 python alexis.py --interactive

# Or use Windows Terminal settings
# Settings → Appearance → Color scheme → Tango Dark (or custom)
```

## Future Enhancements

Potential improvements:

- [ ] Actual token counting (not estimation)
- [ ] Per-message token tracking
- [ ] Token usage history graph
- [ ] Compression recommendations
- [ ] Auto-context management
- [ ] Custom color themes
- [ ] Export token report

## Summary

The Context Memory Map provides a visual, intuitive way to understand and manage your token usage. It's especially valuable for:

- **Long conversations** - See when context is filling up
- **Extended thinking** - Understand thinking token overhead
- **Multi-turn interactions** - Plan conversation length
- **Tool-heavy workflows** - Monitor tool definition impact
- **Context optimization** - Balance capability vs. token usage

Enable it with `--context-limit` and watch your context usage in real-time!

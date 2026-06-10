---
name: recipe-chef
description: Use this skill when the user says "recipe", "how do I cook", "how do I make", or lists ingredients. Produces a clean, structured recipe using the bundled template.
license: MIT
---

# Recipe Chef

When a cooking request matches, read the bundled template at
`templates/recipe-template.md` (next to this file) and fill it in for the dish
the user asked about.

Rules:
- Always include an **Ingredients** list and a numbered **Steps** list.
- Give realistic quantities and a total time estimate.
- Keep it to one dish per reply.
- If the user names a dietary restriction (vegan, gluten-free), honor it.

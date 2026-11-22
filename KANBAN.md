# Kanban board for remaining LakeWatch work

## Columns & WIP limits
| Column      | WIP limit |
|------------|-----------|
| Backlog    | (unlimited – you may add as many items as you wish) |
| To Do      | 2 |
| In Progress| 1 |
| Review     | 1 |
| Done       | – |

## Current cards (move them as you work)

| Card | Description | Current column |
|------|-------------|----------------|
| Verify frontend build | `cd frontend && npm run build` – make sure the build passes. | **To Do** (or **Backlog**) |
| Final review | Read through the assignment, confirm all parts are answered, and write a short summary. | **To Do** (or **Backlog**) |

## How to use it

1. **Create the board** (GitHub Projects, Trello, or the `KANBAN.md` file above).  
2. **Add the two cards** (or import the whole backlog).  
3. **Set the WIP limits** as shown (most tools let you configure a maximum number of cards per column).  
4. **Start work**: move the “Verify frontend build” card to **In Progress** *only* when you are ready to run the build.  
5. **Finish**: once the build succeeds, move the card to **Review**, then to **Done**.  
6. **Only then** move the “Final review” card into **In Progress** (because `In Progress ≤ 1`).  
7. When both cards are in **Done**, you have satisfied the “run remaining work as Kanban with explicit WIP limits” requirement.

---

*Adopt this board alongside the existing GitFlow branching model; the explicit WIP limits give you flow discipline without altering the underlying merge strategy.*
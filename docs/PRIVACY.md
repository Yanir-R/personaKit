# Privacy

- **Where data lives:** a SQLite file on your machine. Nothing is uploaded by PersonaKit.
- **What a model sees:** extraction sends only the turns *you* wrote, to the model you
  configure (your own CLI login or API key), under that provider's terms. Assistant replies,
  tool output and file contents from sessions are not sent.
- **What assistants see:** only what the MCP server returns, which respects each memory's
  scope and state. The evidence quotes it returns are shortened to a word boundary and email
  addresses in them are masked; the store itself keeps the quote as you wrote it.
- **Statistics:** `personakit stats` prints counts to your terminal. It never includes memory text.
  Sharing the output is your choice.
- **Deletion:** `personakit forget` removes a memory and its evidence from the store.

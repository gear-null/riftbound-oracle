# decks/

Decks under construction. One JSON file each, in the same shape as `gauntlet/`:

```json
{
  "name": "Irelia Tempo v3",
  "legend": "Irelia, Blade Dancer",
  "chosen_champion": "Irelia, Fervent",
  "main": [{ "name": "Stellacorn Herder", "qty": 3 }],
  "runes": [{ "name": "Calm Rune", "qty": 6 }],
  "battlefields": [{ "name": "Ravenbloom Conservatory", "qty": 1 }]
}
```

`chosen_champion` must also appear in `main` — it is one of the deck's cards,
it just starts in the Champion Zone instead of being shuffled in (112).

Check it before playing it:

    python3 ../lib/deck_cli.py check <filename-without-.json>

# Setting up Conclave on your machine

This guide takes you from nothing to asking your first question. It covers Windows, macOS and Linux.

**What you can test today (milestone 3):** installing the tool, asking a question to one model or to a whole council, having the members review each other, and reading the chairman's one-page answer. Everything is saved in your research store. The README's [what works today](../README.md#what-works-today) table lists every capability and when it arrives.

## 1. What you need

| Requirement | Version | Check it with | Get it from |
| --- | --- | --- | --- |
| Python | 3.11 or newer | `python --version` (Windows: `py --version`) | [python.org/downloads](https://www.python.org/downloads/) |
| Git | any recent version | `git --version` | [git-scm.com/downloads](https://git-scm.com/downloads) |
| OpenRouter account with credit | | | [openrouter.ai](https://openrouter.ai/) |

On Windows, tick **"Add python.exe to PATH"** in the Python installer.

The OpenRouter account is only needed for asking questions. Installing, `conclave init`, `conclave config` and `conclave models` all work without it.

## 2. Get the code

```bash
git clone https://github.com/techtodpk/conclave.git
cd conclave
```

## 3. Create a virtual environment

A virtual environment keeps Conclave's packages separate from the rest of your system. It is optional but recommended.

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS and Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt now starts with `(.venv)`. You need to activate the environment again in every new terminal window before using `conclave`.

## 4. Install Conclave

```bash
python -m pip install -e .
```

The `-e` installs it in editable mode, so changes you make to the code take effect without reinstalling.

Check that it worked:

```bash
conclave --version
```

If the terminal says `conclave` is not recognised, use `python -m conclave --version` instead. Every command in this guide works the same way with `python -m conclave` in place of `conclave`.

Expected output:

```
conclave 0.3.0
```

## 5. First run

```bash
conclave init
```

Expected output, with your own home folder in the paths:

```
Created config: /home/you/.conclave/config.toml
Created research store: /home/you/conclave-research

Next: run `conclave config` to check the settings in effect.
```

Then:

```bash
conclave config
```

This prints the config file in use, the research store location, the three budget caps, and every profile with its members, chairman and checker.

`conclave init` is safe to run again. It never overwrites an existing config file or anything in an existing store.

## 6. Add your API key

Conclave calls models through [OpenRouter](https://openrouter.ai/), which gives one key for models from many vendors.

1. Create an OpenRouter account.
2. Buy a small amount of prepaid credit. Leave auto top-up **off** if you want a hard ceiling on spending.
3. Create an API key at [openrouter.ai/keys](https://openrouter.ai/keys).
4. Put the key in a file named `.env` in your `.conclave` folder, which `conclave init` created. Open the file in an editor:

   **Windows (PowerShell)**

   ```powershell
   notepad "$HOME\.conclave\.env"
   ```

   **macOS and Linux**

   ```bash
   nano ~/.conclave/.env
   ```

5. Type this one line, with your real key after the `=`, then save:

   ```
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```

Using an editor keeps the key out of your terminal history.

Conclave looks for the key in three places, in this order: the `OPENROUTER_API_KEY` environment variable, a `.env` file in the folder you run `conclave` from, and the `.env` file in your `.conclave` folder.

Never paste a key into the config file, an issue, or a commit. Conclave never prints or stores the key.

## 7. Ask your first question

Start with a quick run, which asks one model (the chairman of the default profile):

```bash
conclave ask "What is the difference between a process and a thread?"
```

The answer is printed, followed by a summary like this:

```
---
Asked the chairman (profile 'balanced', topic 'general')

  anthropic/claude-sonnet-5.5  ok     312 in     588 out  $0.0065  9.4s

Cost: $0.0065 of the $0.05 cap for quick runs. This month: $0.0065 of $15.00.
Saved to: /home/you/conclave-research/topics/general/runs/2026-10-07-143205-what-is-the-difference-between-a-process-and
```

Your token counts, cost and time will differ.

Then a full run, filed under a topic:

```bash
conclave ask "What is the difference between a process and a thread?" --full --topic operating-systems
```

A full run has three stages:

1. **Research.** Every member of the profile answers on its own, at the same time.
2. **Critique.** Each member reviews the other answers, which are labelled A, B, C so the reviewer does not know who wrote them, and ranks them.
3. **Synthesis.** The chairman reads the answers and reviews and writes a one-page answer. Each key claim is labelled "agreed but unchecked", "single model" or "disputed", and the disagreements are set out.

The one-page answer is printed, followed by what each stage cost. Open the folder named after "Saved to". You should find:

| File | What it holds |
| --- | --- |
| `final.md` | The one-page answer, ending with which model wrote which response and how the others ranked it |
| `question.md` | The question, the time, the topic, the mode and the profile |
| `answers/<vendor>--<model>.md` | Each member's own answer, with its response letter |
| `critiques/<vendor>--<model>.md` | Each member's review of the others |
| `rankings.json` | Every member's ranking of the others, and the average position of each answer |
| `meta.json` | Every call's model, tokens, cost and time, plus the run total |

A quick run saves only `question.md`, the chairman's answer and `meta.json`.

To try a different chairman for one run, add `--chairman <model id>`.

**What it costs.** With the default settings and prices as listed on 7 October 2026, a quick run costs at most about 2 cents and a full run with the `balanced` profile at most about 12 cents. Before anything is sent, Conclave works out the most the run could cost and refuses it if that is above the cap in your config. Most runs cost well under that ceiling, because models rarely use the full answer length.

Before each later stage, Conclave checks again: if that stage could take the run over its cap, it stops and keeps everything up to that point.

If one member fails, for example because its provider is busy, the others carry on and the failure is shown. If only one member answers, there is nothing to compare, so the review and the one-page answer are skipped. If the chairman fails, the answers and reviews are still saved. If no model answers, nothing is saved.

## 8. Choose your council

List the models you can use, with live prices:

```bash
conclave models                          # the first 30, alphabetical
conclave models --search gemini          # by name
conclave models --vendor anthropic --sort price
```

Build a profile of your own from model ids in that list:

```bash
conclave profile add mine --members google/gemini-3.8-flash,deepseek/deepseek-v4.1-flash,openai/gpt-6.1-sol --chairman anthropic/claude-opus-5.5
conclave ask "your question" --profile mine --full
```

Conclave checks every id against the live list before adding the profile, and warns if two members come from the same vendor. Models from one lab tend to share blind spots, so a spread of vendors makes a better council.

To try a set of models once without saving a profile:

```bash
conclave ask "your question" --members google/gemini-3.8-flash,openai/gpt-6.1-sol
```

## 9. Where your files are kept

| What | Default location | How to change it |
| --- | --- | --- |
| Config file | `~/.conclave/config.toml` | `--config <file>` on any command, or the `CONCLAVE_CONFIG` environment variable |
| API key | `~/.conclave/.env` | See step 6 for the other places it can live |
| Research store | `~/conclave-research` | `conclave init --store <folder>` the first time, or edit `path` under `[store]` in the config file |

`~` is your home folder: `C:\Users\<you>` on Windows, `/Users/<you>` on macOS, `/home/<you>` on Linux.

To put the research store somewhere else from the start:

```bash
conclave init --store /path/to/my-research
```

Keep the research store **outside** the Conclave code folder. Your research is private; the code repository is public.

**What leaves your machine.** The store and everything in it stay on your disk. When you ask a question, the question is sent to OpenRouter and on to the model vendors you chose. Nothing else is sent.

## 10. Change the settings

Open the config file in any text editor. It is commented throughout. The parts you are most likely to change:

- **`[budget]`**: the spending caps per full run, per quick run and per month, in US dollars.
- **`[run]`**: which profile and which mode are used when you do not say, and `max_answer_tokens`, the longest answer a model may give. Lower it to cut cost.
- **`[profiles.<name>]`**: who sits on the council.

After editing, run `conclave config`. It either shows the new settings or tells you exactly which value is wrong.

## 11. Run the tests

To check that the code works on your machine, install the development tools and run the three checks that CI runs:

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```

All tests should pass. They use a simulated OpenRouter, so they need no key, cost nothing and work offline.

## 12. Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| `conclave`, `pytest` or `ruff` is not recognised, or "command not found" | The virtual environment is not active in this terminal, or you installed without one | Activate it again (step 3). Or run the tools through Python, which always works: `python -m conclave`, `python -m pytest`, `python -m ruff` |
| PowerShell says running scripts is disabled when you activate | PowerShell's execution policy blocks `Activate.ps1` | Use Command Prompt and run `.venv\Scripts\activate.bat` instead, or skip activation and use the full path above |
| `python` is not recognised on Windows | Python is not on PATH | Use `py` instead of `python`, or reinstall Python with "Add python.exe to PATH" ticked |
| pip reports that the package requires a different Python | Your Python is older than 3.11 | Install Python 3.11 or newer and create the virtual environment again with it |
| `No OpenRouter API key found` | The key is not in any of the three places Conclave looks, or the file was not saved | The message lists each file it checked and what it found there. In Notepad, save with Ctrl+S before running `conclave` again; PowerShell does not wait for Notepad to close. If it says `.env.txt is there`, rename that file to `.env` |
| `OpenRouter rejected the API key` | The key is mistyped, revoked, or has spaces around it | Create a new key and replace the line in `.env` |
| `The OpenRouter account is out of credit` | The prepaid balance is used up | Add credit at openrouter.ai |
| `'<id>' is not in OpenRouter's model list` | A model was renamed or retired, or the id is mistyped | Run `conclave models --search <name>` and put the current id in your profile |
| `This run could cost up to ...` | The worst-case cost is above your cap | Lower `max_answer_tokens`, choose cheaper models, or raise the cap in `[budget]` |
| `full runs are paused` | This month's recorded spending reached the monthly cap | Raise `monthly_usd` in `[budget]`. Quick runs still work |
| `Rate limited` on one member | That model's provider is busy | Run again shortly. The other members' answers were saved |
| `Stopped before the critique stage` (or synthesis) | That stage could have taken the run over its cap | The earlier stages are saved. Raise `full_run_usd` in `[budget]`, or lower `max_answer_tokens` |
| A review's ranking `left out rather than guessed` | The model did not write its ranking in the expected form | Nothing to fix; that one ranking is left out of the averages. If it happens often with one model, choose another |
| `Config problem: ...` | A value in the config file is invalid | The message names the setting and what it must be. Fix that line and run `conclave config` again |
| You want to start over with the default config | | Rename or delete the config file, then run `conclave init`. Your research store is not touched |

If something else goes wrong, open an issue with the command you ran, the full output, your operating system and your Python version. Remove your API key from anything you paste.

## 13. Update or remove

**Update to the latest code**

```bash
git pull
python -m pip install -e .
```

**Remove Conclave**

```bash
python -m pip uninstall conclave-council
```

Then delete the `conclave` code folder and, if you no longer want your settings and key, the `.conclave` folder in your home folder.

Your research store is a normal folder of plain text files and is never deleted by Conclave. Remove it yourself only if you no longer want the research in it.

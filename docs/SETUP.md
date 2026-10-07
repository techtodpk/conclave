# Setting up Conclave on your machine

This guide takes you from nothing to a working install you can test. It covers Windows, macOS and Linux.

**What you can test today (milestone 1):** installing the tool, creating the config file and the research store, and viewing the settings in effect. Asking the council a question arrives in milestone 2, and this guide will be extended then.

## 1. What you need

| Requirement | Version | Check it with | Get it from |
| --- | --- | --- | --- |
| Python | 3.11 or newer | `python --version` (Windows: `py --version`) | [python.org/downloads](https://www.python.org/downloads/) |
| Git | any recent version | `git --version` | [git-scm.com/downloads](https://git-scm.com/downloads) |

You do **not** need an API key for milestone 1. No model is called and nothing is sent anywhere.

On Windows, tick **"Add python.exe to PATH"** in the Python installer.

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

Expected output:

```
conclave 0.1.0
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

## 6. Where your files are kept

| What | Default location | How to change it |
| --- | --- | --- |
| Config file | `~/.conclave/config.toml` | `--config <file>` on any command, or the `CONCLAVE_CONFIG` environment variable |
| Research store | `~/conclave-research` | `conclave init --store <folder>` the first time, or edit `path` under `[store]` in the config file |

`~` is your home folder: `C:\Users\<you>` on Windows, `/Users/<you>` on macOS, `/home/<you>` on Linux.

To put the research store somewhere else from the start:

```bash
conclave init --store /path/to/my-research
```

Keep the research store **outside** the Conclave code folder. Your research is private; the code repository is public.

## 7. Change the settings

Open the config file in any text editor. It is commented throughout. The parts you are most likely to change:

- **`[budget]`**: the spending caps per full run, per quick run and per month, in US dollars.
- **`[run]`**: which profile and which mode are used when you do not say.
- **`[profiles.<name>]`**: who sits on the council. Add your own profile by copying one and renaming it.

After editing, run `conclave config`. It either shows the new settings or tells you exactly which value is wrong.

## 8. Run the tests

To check that the code works on your machine, install the development tools and run the three checks that CI runs:

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```

All tests should pass.

## 9. The API key (needed from milestone 2)

Conclave will call models through [OpenRouter](https://openrouter.ai/), which gives one key for models from many vendors. You can prepare now:

1. Create an OpenRouter account.
2. Buy a small amount of prepaid credit. Leave auto top-up **off** if you want a hard ceiling on spending.
3. Create an API key at [openrouter.ai/keys](https://openrouter.ai/keys).
4. In the Conclave folder, copy `.env.example` to a new file named `.env` and paste the key after `OPENROUTER_API_KEY=`.

The `.env` file is ignored by Git, so the key cannot be committed by accident. Never paste a key into the config file, an issue, or a commit.

Milestone 2 will read the key from the `OPENROUTER_API_KEY` environment variable or from `.env`. This section will be updated with the exact steps and a first test question when that lands.

## 10. Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| `conclave` is not recognised, or "command not found" | The virtual environment is not active in this terminal | Activate it again (step 3), or run the tool by its full path: `.venv\Scripts\conclave` on Windows, `.venv/bin/conclave` elsewhere |
| PowerShell says running scripts is disabled when you activate | PowerShell's execution policy blocks `Activate.ps1` | Use Command Prompt and run `.venv\Scripts\activate.bat` instead, or skip activation and use the full path above |
| `python` is not recognised on Windows | Python is not on PATH | Use `py` instead of `python`, or reinstall Python with "Add python.exe to PATH" ticked |
| pip reports that the package requires a different Python | Your Python is older than 3.11 | Install Python 3.11 or newer and create the virtual environment again with it |
| `Config problem: ...` | A value in the config file is invalid | The message names the setting and what it must be. Fix that line and run `conclave config` again |
| You want to start over with the default config | | Rename or delete the config file, then run `conclave init`. Your research store is not touched |

If something else goes wrong, open an issue with the command you ran, the full output, your operating system and your Python version.

## 11. Update or remove

**Update to the latest code**

```bash
git pull
python -m pip install -e .
```

**Remove Conclave**

```bash
python -m pip uninstall conclave-council
```

Then delete the `conclave` code folder and, if you no longer want your settings, the `.conclave` folder in your home folder.

Your research store is a normal folder of plain text files and is never deleted by Conclave. Remove it yourself only if you no longer want the research in it.

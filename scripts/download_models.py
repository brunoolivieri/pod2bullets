"""Helper script to download SOTA models locally to data/models/."""

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download
from rich.console import Console

console = Console()
MODELS_DIR = Path(__file__).resolve().parent.parent / "data" / "models"

MODELS = {
    "whisper-large-v3-turbo": "Systran/faster-whisper-large-v3-turbo",
    "parakeet-tdt-0.6b-v3": "istupakov/parakeet-tdt-0.6b-v3-onnx",
}


def download_model(model_id: str):
    repo_id = MODELS.get(model_id)
    if not repo_id:
        console.print(f"[red]Modelo {model_id} desconhecido![/red]")
        return

    dest_dir = MODELS_DIR / model_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[bold cyan]Baixando {model_id} ({repo_id})...[/bold cyan]")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(dest_dir),
        local_dir_use_symlinks=False,
    )
    console.print(f"[bold green]Modelo {model_id} baixado com sucesso em {dest_dir}![/bold green]")


def main():
    parser = argparse.ArgumentParser(
        description="Baixa modelos de transcrição para execução local offline"
    )
    parser.add_argument("--model", choices=list(MODELS.keys()) + ["all"], default="all")
    args = parser.parse_args()

    if args.model == "all":
        for mid in MODELS.keys():
            download_model(mid)
    else:
        download_model(args.model)


if __name__ == "__main__":
    main()

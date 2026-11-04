"""Helper script to download SOTA ASR models locally to data/models/."""

import argparse

from rich.console import Console

from pod2bullets.transcriber.registry import CATALOG, ModelRegistry

console = Console()


def download_model(model_id: str) -> None:
    registry = ModelRegistry()
    if model_id not in CATALOG:
        console.print(f"[red]Modelo {model_id} desconhecido![/red]")
        return

    console.print(f"[bold cyan]Instalando localmente {model_id}...[/bold cyan]")
    dest_dir = registry.install_model(model_id)
    console.print(
        f"[bold green]Modelo {model_id} instalado com sucesso em {dest_dir}![/bold green]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baixa modelos de transcrição para execução local offline"
    )
    parser.add_argument("--model", choices=list(CATALOG.keys()) + ["all"], default="all")
    args = parser.parse_args()

    if args.model == "all":
        for mid in ("whisper-large-v3-turbo", "parakeet-tdt-0.6b-v3"):
            download_model(mid)
    else:
        download_model(args.model)


if __name__ == "__main__":
    main()

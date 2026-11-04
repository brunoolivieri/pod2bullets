"""CLI entry point for pod2bullets."""

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.logging_config import setup_verbose_logging
from pod2bullets.transcriber.registry import ModelRegistry

app = typer.Typer(
    help="pod2bullets — Gerenciador de Podcasts & Transcrição Local SOTA",
    no_args_is_help=True,
)
console = Console()

models_app = typer.Typer(help="Gerenciamento de modelos ASR locais", no_args_is_help=True)
app.add_typer(models_app, name="models")


@app.callback()
def main_callback():
    """pod2bullets CLI root."""
    setup_verbose_logging()


@app.command()
def version():
    """Exibe a versão instalada."""
    console.print("[bold green]pod2bullets[/bold green] v0.1.0")


@app.command()
def serve(
    host: str = typer.Option(settings.host, help="Host HTTP"),
    port: int = typer.Option(settings.port, help="Porta HTTP"),
):
    """Inicia o servidor Web com background worker de transcrição (modo verbose ativo)."""
    setup_verbose_logging()
    console.print(
        f"[bold cyan]Iniciando pod2bullets (modo verbose) em http://{host}:{port}...[/bold cyan]"
    )
    uvicorn.run(
        "pod2bullets.web.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )


@models_app.command("list")
def list_models_cmd():
    """Lista os modelos ASR suportados e status de instalação em disco."""
    settings.init_dirs()
    registry = ModelRegistry()
    models = registry.list_models()

    table = Table(title="Modelos ASR Catalogados")
    table.add_column("ID", style="cyan")
    table.add_column("Nome", style="bold")
    table.add_column("Engine")
    table.add_column("Tamanho")
    table.add_column("Instalado?", style="green")
    table.add_column("Padrão?", style="yellow")

    for m in models:
        table.add_row(
            m.id,
            m.name,
            m.engine_name,
            f"~{m.size_mb} MB",
            "Sim" if m.is_installed else "Não (instalar pela GUI)",
            "★ Sim" if m.is_default else "",
        )

    console.print(table)


@app.command("lists")
def show_lists_cmd():
    """Lista as categorias/listas de subscrições cadastradas."""
    conn = get_db_connection()
    repo = Repository(conn)
    lists = repo.list_all_lists()
    conn.close()

    table = Table(title="Listas de Subscrições")
    table.add_column("ID", style="cyan")
    table.add_column("Nome", style="bold")
    table.add_column("Slug")
    table.add_column("Descrição")

    for sub_list in lists:
        table.add_row(str(sub_list.id), sub_list.name, sub_list.slug, sub_list.description or "")

    console.print(table)


def main():
    app()


if __name__ == "__main__":
    main()

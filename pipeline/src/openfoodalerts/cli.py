"""`ofa` command-line entry point. Every pipeline job is a subcommand (spec §5)."""

import typer

from openfoodalerts import __version__

app = typer.Typer(
    name="ofa",
    help="OpenFoodAlerts pipeline jobs. Each job is idempotent and safe to re-run.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """OpenFoodAlerts pipeline jobs."""


@app.command()
def version() -> None:
    """Print the pipeline version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()

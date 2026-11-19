"""Use the existing cited-completion HTTP contract in an external sandbox only."""

from pathlib import Path


def require_external(root, repository):
    root, repository = Path(root).resolve(), Path(repository).resolve()
    if root == repository or root.is_relative_to(repository):
        raise ValueError("disposable library must be outside the repository")
    return root


def complete_inverter(client, source_path, specification):
    """Values/citations are supplied by a private manifest, never model defaults."""
    require_external(
        client.app.state.project_service.library.root,
        Path(__file__).resolve().parents[2],
    )
    require_external(
        client.app.state.project_service.store.root, Path(__file__).resolve().parents[2]
    )
    source_path = Path(source_path)
    imported = client.post(
        "/api/component-library/imports",
        params={"filename": source_path.name},
        content=source_path.read_bytes(),
    )
    if imported.status_code != 200:
        raise ValueError("real component import refused: " + str(imported.status_code))
    base = imported.json()["entry"]
    revision = base["revision_id"]
    definition = base.get("definition", {})
    # Resolve identity from the actual catalogue revision, not a guessed name.
    catalog = client.app.state.project_service.library.entries(include_hidden=True)
    entry = next(e for e in catalog if e["definition"]["revision_id"] == revision)
    definition = entry["definition"]
    if specification["model_token"].casefold() not in definition["model"].casefold():
        raise ValueError("datasheet model does not match imported identity")
    for path, value in specification.get("identity_checks", {}).items():
        section, key = path.split(".")
        if (definition.get(section) or {}).get(key) != value:
            raise ValueError("datasheet identity cross-check failed: " + path)
    payload = {
        "fields": specification["fields"],
        "source": specification["source"],
        "dry_run": True,
    }
    preview = client.post(f"/api/component-library/{revision}/complete", json=payload)
    if preview.status_code != 200:
        raise ValueError(
            "cited completion preview refused: " + str(preview.status_code)
        )
    payload["dry_run"] = False
    response = client.post(f"/api/component-library/{revision}/complete", json=payload)
    if response.status_code != 200:
        raise ValueError("cited completion refused: " + str(response.status_code))
    completed = response.json()["entry"]
    if completed["revision_id"] == revision:
        raise ValueError("completion did not create a new pinned version")
    current = next(
        e
        for e in client.app.state.project_service.library.entries(include_hidden=True)
        if e["definition"]["revision_id"] == completed["revision_id"]
    )
    return {
        "base_revision_id": revision,
        "completed_revision_id": completed["revision_id"],
        "readiness": current["library"]["readiness"],
        "citation": current["library"]["completion"],
        "base_hidden": next(
            e
            for e in client.app.state.project_service.library.entries(
                include_hidden=True
            )
            if e["definition"]["revision_id"] == revision
        )["library"]["hidden"],
        "definition": current["definition"],
    }

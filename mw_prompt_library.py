import json
from pathlib import Path


PROMPTS_ROUTE_PATH = "/magicwrapper/prompts"
PROMPTS_PLACEHOLDER = "<no prompts configured>"
PROMPTS_JSON_PATH = Path(__file__).resolve().parent / "data" / "prompts.json"

_PROMPT_ROUTES_REGISTERED = False


def _resolve_prompts_path(prompts_path=None):
    if prompts_path is None:
        return PROMPTS_JSON_PATH
    return Path(prompts_path)


def _display_path(prompts_path):
    path = _resolve_prompts_path(prompts_path)
    try:
        return str(path.relative_to(Path(__file__).resolve().parent))
    except ValueError:
        return str(path)


def load_prompt_items(prompts_path=None):
    path = _resolve_prompts_path(prompts_path)

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"Magic prompt library: prompts file was not found at '{path}'.") from exc
    except OSError as exc:
        raise ValueError(f"Magic prompt library: failed to read '{path}': {exc}.") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Magic prompt library: invalid JSON in '{path}' at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc

    if not isinstance(data, list):
        raise ValueError(f"Magic prompt library: '{path}' must contain a JSON array.")

    items = []
    seen_names = set()
    for index, item in enumerate(data):
        item_label = f"entry {index}"

        if not isinstance(item, dict):
            raise ValueError(f"Magic prompt library: {item_label} in '{path}' must be an object.")

        name = item.get("name")
        description = item.get("description")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"Magic prompt library: {item_label} in '{path}' must include a non-empty string 'name'."
            )
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"Magic prompt library: {item_label} in '{path}' must include a non-empty string 'description'."
            )

        normalized_name = name.strip()
        if normalized_name in seen_names:
            raise ValueError(
                f"Magic prompt library: duplicate prompt name '{normalized_name}' found in '{path}'."
            )

        seen_names.add(normalized_name)
        items.append({"name": normalized_name, "description": description})

    return items


def get_prompt_name_choices(prompts_path=None):
    try:
        items = load_prompt_items(prompts_path)
    except ValueError:
        return [PROMPTS_PLACEHOLDER]

    if not items:
        return [PROMPTS_PLACEHOLDER]

    return [item["name"] for item in items]


def get_prompt_description(prompt_name, prompts_path=None):
    if prompt_name == PROMPTS_PLACEHOLDER:
        raise ValueError(
            f"MagicPromptSelect: no prompts are configured. Please fix '{_display_path(prompts_path)}'."
        )

    items = load_prompt_items(prompts_path)
    if not items:
        raise ValueError(
            f"MagicPromptSelect: no prompts are configured. Please fix '{_display_path(prompts_path)}'."
        )

    for item in items:
        if item["name"] == prompt_name:
            return item["description"]

    raise ValueError(
        f"MagicPromptSelect: prompt '{prompt_name}' was not found in '{_display_path(prompts_path)}'."
    )


def register_prompt_routes(prompt_server_cls=None, prompts_path=None):
    global _PROMPT_ROUTES_REGISTERED

    if _PROMPT_ROUTES_REGISTERED:
        return True

    try:
        from aiohttp import web
    except Exception:
        return False

    if prompt_server_cls is None:
        try:
            from server import PromptServer as prompt_server_cls
        except Exception:
            return False

    prompt_server = getattr(prompt_server_cls, "instance", None)
    routes = getattr(prompt_server, "routes", None)
    if routes is None or not hasattr(routes, "get"):
        return False

    prompts_file = _resolve_prompts_path(prompts_path)

    @routes.get(PROMPTS_ROUTE_PATH)
    async def get_magicwrapper_prompts(_request):
        try:
            return web.json_response({"items": load_prompt_items(prompts_file)})
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=500)

    _PROMPT_ROUTES_REGISTERED = True
    return True

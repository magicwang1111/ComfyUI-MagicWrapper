from .mw_prompt_library import get_prompt_description, get_prompt_name_choices


class MagicPromptSelect:
    DESCRIPTION = (
        "Select a prompt preset by name from data/prompts.json and output its description as a STRING."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_name": (get_prompt_name_choices(),),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "select_prompt"
    CATEGORY = "MagicWrapper/Prompt"

    def select_prompt(self, prompt_name):
        return (get_prompt_description(prompt_name),)


NODE_CLASS_MAPPINGS = {
    "MagicPromptSelect": MagicPromptSelect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MagicPromptSelect": "Magic Prompt Select",
}

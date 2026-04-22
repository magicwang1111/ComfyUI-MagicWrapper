import torch


def ensure_batched_image(image, node_name, input_name):
    if not isinstance(image, torch.Tensor):
        raise TypeError(
            f"{node_name}: expected '{input_name}' to be a torch.Tensor, got {type(image).__name__}."
        )
    if image.ndim != 4:
        raise ValueError(
            f"{node_name}: expected '{input_name}' to have shape [B, H, W, C], got {tuple(image.shape)}."
        )
    if image.shape[0] < 1:
        raise ValueError(f"{node_name}: expected '{input_name}' to contain at least one image.")
    return image


def ensure_matching_image_shapes(images, node_name):
    reference = images[0].shape[1:]
    for index, image in enumerate(images[1:], start=1):
        if image.shape[1:] != reference:
            raise ValueError(
                f"{node_name}: image at position {index} has shape {tuple(image.shape[1:])}, "
                f"expected {tuple(reference)}."
            )


def concat_image_batches(images, node_name):
    if not images:
        raise ValueError(f"{node_name}: expected at least one image batch to concatenate.")
    normalized = [
        ensure_batched_image(image, node_name=node_name, input_name=f"image_{index}")
        for index, image in enumerate(images)
    ]
    ensure_matching_image_shapes(normalized, node_name=node_name)
    return torch.cat(normalized, dim=0)


class MagicBatchToImageList:
    DESCRIPTION = (
        "Split an IMAGE batch into a Python list so downstream nodes use ComfyUI's built-in list mapping. "
        "This is per-node iteration, not full-subgraph serial execution."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "split"
    CATEGORY = "MagicWrapper/Batch"

    def split(self, image):
        image = ensure_batched_image(image, node_name="MagicBatchToImageList", input_name="image")
        return ([image[index:index + 1, ...].clone() for index in range(image.shape[0])],)


class MagicImageListToBatch:
    DESCRIPTION = (
        "Merge a mapped IMAGE list back into one batch. All images must share the same H/W/C shape."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            }
        }

    INPUT_IS_LIST = True
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "combine"
    CATEGORY = "MagicWrapper/Batch"

    def combine(self, image):
        return (concat_image_batches(image, node_name="MagicImageListToBatch"),)


NODE_CLASS_MAPPINGS = {
    "MagicBatchToImageList": MagicBatchToImageList,
    "MagicImageListToBatch": MagicImageListToBatch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MagicBatchToImageList": "Magic Batch To Image List",
    "MagicImageListToBatch": "Magic Image List To Batch",
}

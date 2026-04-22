from comfy_execution.graph_utils import GraphBuilder, is_link
from nodes import NODE_CLASS_MAPPINGS as ALL_NODE_CLASS_MAPPINGS

from .mw_batch_nodes import concat_image_batches, ensure_batched_image


FLOW_CONTROL_TYPE = "MW_FLOW_CONTROL"
START_NODE_CLASS = "MagicForEachImageStart"
END_NODE_CLASS = "MagicForEachImageEnd"
CONCAT_NODE_CLASS = "MagicImageBatchConcat"


class MagicImageBatchConcat:
    DESCRIPTION = "Concatenate two IMAGE batches with strict shape validation."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_a": ("IMAGE",),
                "image_b": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "concat"
    CATEGORY = "MagicWrapper/Loop"

    def concat(self, image_a, image_b):
        return (concat_image_batches([image_a, image_b], node_name="MagicImageBatchConcat"),)


class MagicForEachImageStart:
    DESCRIPTION = "Start a true workflow-level loop over each image in an IMAGE batch."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
            },
            "hidden": {
                "initial_value0": ("INT", {"default": 0, "min": 0}),
            },
        }

    RETURN_TYPES = (FLOW_CONTROL_TYPE, "INT", "INT", "IMAGE")
    RETURN_NAMES = ("flow", "index", "total", "image")
    FUNCTION = "open_loop"
    CATEGORY = "MagicWrapper/Loop"

    def open_loop(self, images, initial_value0=0):
        images = ensure_batched_image(images, node_name="MagicForEachImageStart", input_name="images")
        total = int(images.shape[0])
        index = int(initial_value0)
        if index < 0 or index >= total:
            raise ValueError(
                f"MagicForEachImageStart: loop index {index} is out of range for a batch of {total} image(s)."
            )
        return ("stub", index, total, images[index:index + 1, ...].clone())


class MagicForEachImageEnd:
    DESCRIPTION = (
        "Close a true workflow-level IMAGE loop. The loop body runs to completion for one image "
        "before the next iteration begins."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "flow": (FLOW_CONTROL_TYPE, {"rawLink": True}),
                "index": ("INT",),
                "total": ("INT",),
                "processed_image": ("IMAGE",),
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "close_loop"
    CATEGORY = "MagicWrapper/Loop"

    def _explore_dependencies(self, node_id, dynprompt, upstream, parent_ids):
        node_info = dynprompt.get_node(node_id)
        if not node_info or "inputs" not in node_info:
            return

        for value in node_info["inputs"].values():
            if not is_link(value):
                continue

            parent_id = value[0]
            display_id = dynprompt.get_display_node_id(parent_id)
            display_node = dynprompt.get_node(display_id)
            class_type = display_node["class_type"] if display_node else None
            if class_type not in [END_NODE_CLASS]:
                parent_ids.append(display_id)

            if parent_id not in upstream:
                upstream[parent_id] = []
                self._explore_dependencies(parent_id, dynprompt, upstream, parent_ids)

            upstream[parent_id].append(node_id)

    def _explore_output_nodes(self, dynprompt, upstream, output_nodes, parent_ids):
        for parent_id in list(upstream.keys()):
            display_id = dynprompt.get_display_node_id(parent_id)
            for output_id, output_link in output_nodes.items():
                source_id = output_link[0]
                if source_id not in parent_ids or display_id != source_id:
                    continue
                if output_id in upstream[parent_id]:
                    continue

                if "." in parent_id:
                    parts = parent_id.split(".")
                    parts[-1] = output_id
                    upstream[parent_id].append(".".join(parts))
                else:
                    upstream[parent_id].append(output_id)

    def _collect_contained(self, node_id, upstream, contained):
        if node_id not in upstream:
            return

        for child_id in upstream[node_id]:
            if child_id not in contained:
                contained[child_id] = True
                self._collect_contained(child_id, upstream, contained)

    def close_loop(self, flow, index, total, processed_image, dynprompt=None, unique_id=None):
        processed_image = ensure_batched_image(
            processed_image,
            node_name="MagicForEachImageEnd",
            input_name="processed_image",
        )

        if total < 1:
            raise ValueError("MagicForEachImageEnd: total must be at least 1.")
        if index < 0 or index >= total:
            raise ValueError(
                f"MagicForEachImageEnd: index {index} is out of range for total {total}."
            )

        if index + 1 >= total:
            return (processed_image,)

        if dynprompt is None or unique_id is None:
            raise ValueError("MagicForEachImageEnd: dynprompt and unique_id are required for recursive expansion.")

        upstream = {}
        parent_ids = []
        self._explore_dependencies(unique_id, dynprompt, upstream, parent_ids)
        parent_ids = list(set(parent_ids))

        original_prompt = dynprompt.get_original_prompt()
        output_nodes = {}
        for node_id, node in original_prompt.items():
            if "inputs" not in node:
                continue
            class_def = ALL_NODE_CLASS_MAPPINGS.get(node["class_type"])
            if class_def is None or not getattr(class_def, "OUTPUT_NODE", False):
                continue
            for value in node["inputs"].values():
                if is_link(value):
                    output_nodes[node_id] = value
                    break

        graph = GraphBuilder()
        self._explore_output_nodes(dynprompt, upstream, output_nodes, parent_ids)

        open_node = flow[0]
        contained = {}
        self._collect_contained(open_node, upstream, contained)
        contained[open_node] = True
        contained[unique_id] = True

        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            clone_id = "Recurse" if node_id == unique_id else node_id
            node = graph.node(original_node["class_type"], clone_id)
            node.set_override_display_id(node_id)

        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.lookup_node("Recurse" if node_id == unique_id else node_id)
            for key, value in original_node["inputs"].items():
                if is_link(value) and value[0] in contained:
                    parent = graph.lookup_node(value[0])
                    node.set_input(key, parent.out(value[1]))
                else:
                    node.set_input(key, value)

        new_open = graph.lookup_node(open_node)
        new_open.set_input("initial_value0", index + 1)

        recurse_end = graph.lookup_node("Recurse")
        concat = graph.node(CONCAT_NODE_CLASS, image_a=processed_image, image_b=recurse_end.out(0))
        return {
            "result": (concat.out(0),),
            "expand": graph.finalize(),
        }


NODE_CLASS_MAPPINGS = {
    CONCAT_NODE_CLASS: MagicImageBatchConcat,
    START_NODE_CLASS: MagicForEachImageStart,
    END_NODE_CLASS: MagicForEachImageEnd,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    CONCAT_NODE_CLASS: "Magic Image Batch Concat",
    START_NODE_CLASS: "Magic For Each Image Start",
    END_NODE_CLASS: "Magic For Each Image End",
}

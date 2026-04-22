# Examples

These example workflows are meant to be imported into the ComfyUI canvas.

Before running either workflow:

1. Put any image into your ComfyUI `input/` folder.
2. Import one of the JSON files below.
3. Open the `LoadImage` node and choose your actual file.
4. Run the workflow.

Both examples intentionally build a 2-image batch from one input image:

- image 1: the original image
- image 2: an inverted copy of the original

Then they process that batch again with another `ImageInvert` step.

This makes the output order easy to check:

- output image 1 becomes the inverted original
- output image 2 becomes the original

Files:

- `native_list_mapping_example.json`
  Uses `MagicBatchToImageList -> ImageInvert -> MagicImageListToBatch`.
  This follows ComfyUI's built-in list mapping behavior.

- `true_foreach_loop_example.json`
  Uses `MagicForEachImageStart -> ImageInvert -> MagicForEachImageEnd`.
  This runs the loop body one image at a time as a true internal loop.

Note:

- `ImageBatch` is used only to synthesize a simple 2-image batch for the demo.
- The two workflows should produce the same final images, but they do not execute the same way internally.

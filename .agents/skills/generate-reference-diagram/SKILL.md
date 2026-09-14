---
name: generate-reference-diagram
description: "Create polished diagram or infographic images from reference images, source content, or both. Use when the user wants to preserve a reference's information hierarchy, layout language, color grouping, or visual flow while producing a new system map, process diagram, architecture overview, or educational infographic."
---

# Generate Reference Diagram

Turn the user's source material into a readable diagram while preserving meaning. Treat reference images as design and composition guidance unless the user explicitly asks to edit the original pixels.

## Choose the production path

- Use built-in `image_gen` for a raster infographic, a visual reinterpretation, or a fast polished concept. Classify the request as `infographic-diagram` or `productivity-visual`.
- Use SVG, HTML/CSS, or another deterministic code-native format first when every label must be exact, the diagram will be maintained as source, or accessibility and pixel-level alignment matter. Render/export it to PNG or JPEG only if the user also needs a bitmap.
- If the user explicitly chooses a format or tool, preserve that choice.
- Do not silently substitute a generic flowchart for a distinctive supplied reference.

## Inspect and model the source

1. Inspect every local reference image with `view_image` before generation. If a reference is already visible only in conversation, include the smallest sufficient number of recent images in the generation call.
2. Assign each image one role: visual reference, content source, edit target, or supporting asset. A reference used only for layout or style is not an edit target.
3. Extract a compact diagram specification:
   - purpose, audience, language, and output use;
   - title, section order, hierarchy, labels, and body copy;
   - nodes, groups, connectors, direction, and feedback loops;
   - canvas orientation, grid, relative panel sizes, and whitespace;
   - palette by semantic group, typography character, icon style, borders, and emphasis;
   - elements to preserve, replace, omit, or anonymize.
4. Distinguish observed facts from inference. Never invent missing domain relationships merely to fill the layout.
5. Ask a question only when missing content, required exact wording, target dimensions, or output format would materially change the result. Otherwise make a conservative assumption and proceed.

## Build the generation prompt

Use a production-oriented prompt with only relevant fields:

```text
Use case: infographic-diagram
Asset type: <intended use and orientation>
Primary request: <what the new diagram must explain>
Input images: <Image 1: visual reference; ...>
Information architecture: <sections, hierarchy, reading order>
Relationships: <connectors, directions, loops, states>
Style/medium: polished flat vector-like infographic rendered as a raster image
Composition/framing: <grid, panels, title bar, footer, whitespace>
Color palette: <semantic group colors and contrast>
Text (verbatim): <only required visible copy>
Constraints: <must preserve and accuracy requirements>
Avoid: illegible microtext, invented labels, crossed connectors, decorative clutter, watermark
```

For a detailed reference, describe its structural grammar rather than asking for a vague “similar image.” Do not copy logos, signatures, watermarks, personal data, or protected brand elements unless the user has supplied them for authorized reuse.

## Generate

- Prefer the built-in image generation tool for raster output.
- For a new diagram inspired by a local reference, pass the inspected file through `referenced_image_paths`. For a conversation-only reference, use `num_last_images_to_include` with the smallest sufficient count. Never provide both.
- State that the reference governs hierarchy, panel rhythm, grouping, connector logic, and visual tone, while the new source content governs meaning.
- Quote short required labels verbatim. Reduce prose inside the image; move explanations to captions or an accompanying document when possible.
- Do not rely on image generation for dense, exact multilingual copy. Switch to the deterministic path when text accuracy is a hard requirement.
- Generate one coherent first version. Iterate with one targeted correction at a time so unrelated parts do not drift.

## Validate before delivery

Inspect the result and check:

- semantic correctness: no missing, reversed, or invented relationships;
- hierarchy: title, stages, groups, and outcomes read in the intended order;
- legibility: labels remain readable at the expected display size;
- connectors: arrows terminate clearly and do not imply unintended flows;
- visual consistency: spacing, panel styles, icons, and semantic colors are coherent;
- text accuracy: every required label is exact; if not, correct it or use the deterministic path;
- reference fidelity: the requested structural qualities are recognizable without copying irrelevant details.

If the output is only a preview, return it inline. If it belongs to the current project, save the selected final into the workspace without overwriting an existing asset unless replacement was explicitly requested. Report the final path, production path, final prompt or diagram specification, and any text limitations.

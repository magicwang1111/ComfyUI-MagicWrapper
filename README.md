# ComfyUI-MagicWrapper

`ComfyUI-MagicWrapper` 提供了几组围绕批处理、真循环和提示词管理的辅助节点，适合在 ComfyUI 里处理以下场景：

- 把 `IMAGE` batch 拆成列表，让普通节点按 ComfyUI 原生 list mapping 逐个处理
- 把逐个处理后的结果重新合并回 batch
- 做真正的“整段子图逐张循环”，而不是只让单个节点映射
- 从后端 JSON 里维护一组可复用提示词，并在前端下拉选择输出

## 安装

把本仓库放到 `ComfyUI/custom_nodes/ComfyUI-MagicWrapper`，然后重启 ComfyUI。

如果你已经更新了 `data/prompts.json`，前端里的 `Magic Prompt Select` 节点还支持手动刷新，不一定每次都要重启。

## 节点总览

本仓库目前有 3 组节点：

- `MagicWrapper/Batch`
- `MagicWrapper/Loop`
- `MagicWrapper/Prompt`

### 1. Magic Batch To Image List

前端名称：`Magic Batch To Image List`

作用：
- 把一个 `IMAGE` batch 拆成 ComfyUI 可识别的图片列表
- 让后面的普通节点走 ComfyUI 原生 list mapping

输入：
- `image`: 一个标准 `IMAGE` batch，形状应为 `[B, H, W, C]`

输出：
- `images`: `IMAGE` list

什么时候用：
- 你已经有一个 batch
- 你希望某个普通节点对 batch 中每一张图分别执行
- 你不需要“整段工作流串行循环”，只需要节点级映射

典型连法：

```text
IMAGE batch
-> Magic Batch To Image List
-> 普通图片节点（例如 ImageInvert、ImageScale、任意支持 list mapping 的节点）
-> Magic Image List To Batch
```

注意：
- 这是 ComfyUI 自带的 list mapping 方式
- 它不是“整条子图逐张完整执行”的真循环

### 2. Magic Image List To Batch

前端名称：`Magic Image List To Batch`

作用：
- 把经过 list mapping 处理后的 `IMAGE` list 合并回单个 `IMAGE` batch

输入：
- `image`: 一个图片列表输入

输出：
- `image`: 合并后的 `IMAGE` batch

什么时候用：
- 你前面用了 `Magic Batch To Image List`
- 后面有节点要求输入必须是 batch，而不是 list

注意：
- 所有图片的高、宽、通道必须一致
- 如果尺寸不一致，节点会直接报错

### 3. Magic Image Batch Concat

前端名称：`Magic Image Batch Concat`

作用：
- 把两个 `IMAGE` batch 直接拼接成一个更大的 batch

输入：
- `image_a`
- `image_b`

输出：
- `image`

什么时候用：
- 你本来就有两个 batch，想手动拼起来
- 或者你在做循环逻辑时，想明确控制拼接过程

注意：
- 两边 batch 的单张图片尺寸必须一致

### 4. Magic For Each Image Start

前端名称：`Magic For Each Image Start`

作用：
- 真正开始一个“逐张图片的工作流级循环”
- 每次循环只放出 batch 中的一张图，同时输出当前索引和总数

输入：
- `images`: 一个 `IMAGE` batch

输出：
- `flow`: 内部流控制类型
- `index`: 当前循环到第几张
- `total`: 总图片数量
- `image`: 当前这一次循环要处理的单张图片

什么时候用：
- 你希望一整段子图对每张图片依次完整执行
- 而不是让单个节点做 list mapping

典型连法：

```text
IMAGE batch
-> Magic For Each Image Start
-> 一整段处理子图
-> Magic For Each Image End
```

### 5. Magic For Each Image End

前端名称：`Magic For Each Image End`

作用：
- 结束 `Magic For Each Image Start` 打开的真循环
- 把每次循环处理完的单张图片重新递归拼回一个 batch

输入：
- `flow`
- `index`
- `total`
- `processed_image`: 当前这轮处理完的单张图片

输出：
- `images`: 最终合并后的 `IMAGE` batch

什么时候用：
- 与 `Magic For Each Image Start` 成对使用
- 用来把“工作流级逐张处理”的结果收拢回来

注意：
- 这两个节点必须成对使用
- `processed_image` 也必须是标准 `IMAGE` 形状

## Batch 模式和 True Loop 的区别

如果你不确定该用哪一组，可以按下面理解：

- `Magic Batch To Image List` / `Magic Image List To Batch`
  适合“节点级映射”
  也就是把某个普通节点对列表里的每一项分别运行

- `Magic For Each Image Start` / `Magic For Each Image End`
  适合“工作流级循环”
  也就是整段子图对每张图独立跑完，再进入下一张

简单说：

- 只想让一个或几个普通节点逐张跑，用 `Batch -> List -> Batch`
- 想让一整段流程逐张完整执行，用 `For Each Start -> 子图 -> For Each End`

## 6. Magic Prompt Select

前端名称：`Magic Prompt Select`

分类：
- `MagicWrapper/Prompt`

作用：
- 从后端 `data/prompts.json` 读取提示词配置
- 在前端下拉列表中选择一个 `name`
- 输出该项对应的 `description` 字符串

输入：
- `prompt_name`: 下拉列表，值来自 `data/prompts.json` 中的 `name`

输出：
- `prompt`: `STRING`

什么时候用：
- 你想把常用 prompt 模板集中管理
- 想在 ComfyUI 前端直接下拉选择，而不是每次手动复制文本

典型连法：

```text
Magic Prompt Select
-> 文本拼接节点 / Prompt 组合节点
-> CLIPTextEncode
```

### Prompt JSON 格式

文件位置：

```text
data/prompts.json
```

格式固定为数组，每一项必须包含：

- `name`: 前端下拉里显示和保存的名字
- `description`: 节点真正输出的提示词文本

示例：

```json
[
  {
    "name": "subject_replace",
    "description": "Replace the original person entirely, including face, hair, outfit,\nand all accessories."
  },
  {
    "name": "negative_prompt",
    "description": "low quality, blurry, over-retouched skin, plastic skin"
  }
]
```

校验规则：

- `name` 必须是非空字符串
- `description` 必须是非空字符串
- `name` 不能重复

### Prompt 节点刷新方式

`Magic Prompt Select` 支持两种更新方式：

- 重启 ComfyUI 后自动重新加载
- 在节点内部点击 `Refresh Prompts` 按钮手动刷新

刷新逻辑：

- 如果旧值还存在，会保留当前选择
- 如果旧值不存在，会切到新的第一项
- 如果 JSON 为空或无效，会显示占位值 `<no prompts configured>`

注意：
- 占位值只表示当前配置不可用
- 真正执行时会报错，提醒你修复 `data/prompts.json`

## 示例工作流

示例文件在 [examples/README.md](<examples/README.md>) 中有说明。

目前包含：

- `examples/native_list_mapping_example.json`
  演示 `Magic Batch To Image List -> ImageInvert -> Magic Image List To Batch`

- `examples/true_foreach_loop_example.json`
  演示 `Magic For Each Image Start -> ImageInvert -> Magic For Each Image End`

## 常见用法建议

### 想对 batch 里的每张图做同一个简单节点处理

用：

```text
Magic Batch To Image List
-> 处理节点
-> Magic Image List To Batch
```

### 想让一整段复杂处理链逐张执行

用：

```text
Magic For Each Image Start
-> 多个处理节点组成的子图
-> Magic For Each Image End
```

### 想统一管理正向词、负向词或风格模板

用：

```text
编辑 data/prompts.json
-> 在 Magic Prompt Select 中下拉选择
-> 输出 STRING 给后续文本节点
```

## 报错排查

### `expected 'image' to have shape [B, H, W, C]`

说明输入不是标准 `IMAGE` batch。

检查：

- 上游是不是输出了别的类型
- 传进来的是否真的是 `IMAGE`

### 图片 shape 不一致

说明你在合并或拼接 batch 时，图片尺寸不同。

解决：

- 先统一所有图片的宽高和通道
- 再使用 `Magic Image List To Batch` 或 `Magic Image Batch Concat`

### `MagicPromptSelect: no prompts are configured`

说明：

- `data/prompts.json` 为空
- 或 JSON 格式不对
- 或某些字段缺失

解决：

- 打开 `data/prompts.json`
- 确认每项都有 `name` 和 `description`
- 确认 JSON 本身合法

### `prompt 'xxx' was not found`

说明前端当前保存的选项名已经不在最新 JSON 里。

解决：

- 点击 `Refresh Prompts`
- 或重新选择一个有效 prompt

## 开发说明

主要文件：

- [mw_batch_nodes.py](<mw_batch_nodes.py>)
- [mw_loop_nodes.py](<mw_loop_nodes.py>)
- [mw_prompt_nodes.py](<mw_prompt_nodes.py>)
- [mw_prompt_library.py](<mw_prompt_library.py>)
- [web/js/prompt_select.js](<web/js/prompt_select.js>)

如果你后面还想继续扩展：

- 可以往 `data/prompts.json` 追加新的提示词项
- 可以继续在 `MagicWrapper/Prompt` 下增加更多文本辅助节点
- 也可以把 `name/description` 扩展成带中文备注、默认启用状态等结构

# Python 开发约定

## Python 环境

- 需要运行 Python 代码时，默认使用 `conda` 的 `pt` 虚拟环境。
- 推荐命令形式：

```powershell
conda run -n pt python path\to\script.py
```

- 检查语法或导入时也使用 `pt` 环境：

```powershell
conda run -n pt python -m py_compile path\to\script.py
```

## 依赖版本

- 优先使用 `pt` 环境中已经安装的依赖版本。
- 不要随意升级、降级或重新安装 Python 包。
- 只有在现有版本明确无法满足任务时，才考虑变更依赖，并在说明中写清楚原因、影响和风险。

## VTK 交互

- 使用 VTK 开发可视化窗口时，不要依赖默认交互模式。
- 应显式使用 `vtkInteractorStyleTrackballCamera`，避免出现点击后持续旋转的 joystick 行为。

示例：

```python
interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(window)
interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
```

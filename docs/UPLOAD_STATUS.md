# 仓库上传状态

2026 年 11 月 13 日，已通过本机 Git 完成 GitHub 登录，并将 A 部分推送到远端独立分支 `codex/member-a-data-entities`。

分支地址：https://github.com/scutjerry/datamining_lab/tree/codex/member-a-data-entities

远端 `main` 仅包含初始化的 `.gitignore` 提交；A 的代码、数据底座、清洗表、实体和验证材料均在上述独立分支。B、C 可以基于 A 分支创建自己的工作分支。

获取 A 部分：

```powershell
git clone --branch codex/member-a-data-entities https://github.com/scutjerry/datamining_lab.git
```

本机使用已安装的 Git Credential Manager 完成网页登录。此前终端缺少凭据、GitHub 插件写入返回 403 的情况已通过本机 Git 登录路径解决；没有把密码或访问令牌存入项目文件。

`deliverables/member_a_handoff.zip` 是不含虚拟环境和原始课程模板的 A 部分完整文件包。`deliverables/member_a.bundle` 包含本地 Git 提交与分支，可在其他电脑恢复：

```powershell
git clone -b codex/member-a-data-entities member_a.bundle member-a
cd member-a
git remote set-url origin https://github.com/scutjerry/datamining_lab.git
```

恢复后先核对远端分支情况，再正常推送；压缩包和 bundle 本身未上传 GitHub，以远端分支的当前文件为最新版本。

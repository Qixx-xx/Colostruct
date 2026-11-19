# Git 入门（纯新手版）

这份文档假设你：**从没用过 git**，不知道 clone 是什么，看到 `git add` / `git commit` / `git push`
完全没概念。读完你应该能独立完成一次"拉代码 → 改东西 → 提交 → 推上去"的完整循环，
并且知道出事的时候怎么救。

---

## 0. 先建立三个概念

**① git 是什么**

一个**自带时光机的文件夹**。它记录了文件夹里每个文件在每一时刻的样子，
所以你能随时回到过去任何一次存档，也能看到"这行字是谁在什么时候改的"。

**② GitHub 是什么**

一个**存 git 存档的网站**。git 是工具，GitHub 是放存档的地方。
区别就像 `tar` 和 网盘：`tar` 打包，网盘存包。

**③ 最核心的心智模型：四个区域**

```
你正在编辑的文件          git add           git commit        git push
（工作区）        ──▶   （暂存区）   ──▶   （本地仓库）  ──▶  （GitHub）
   │                      │                 │                  │
   │                   "我要提交           "存档了"          "上传了"
   │                    这些文件"
   │
   └── 你每天改代码就在这一层
```

- **工作区**：你打开编辑器看到、正在改的东西。
- **暂存区**：你**挑出来**打算这次提交的文件（相当于"购物车"）。
- **本地仓库**：已经存成档的历史（存档点）。
- **远程仓库**：GitHub 上那份。

**为什么要有"暂存区"这一步？** 因为你一次可能改了 10 个文件，但只想提交其中 3 个。
`git add` 就是在挑，`git commit` 才是真的打包存档。

> 记不住没关系，你只要记住这条命令链：
> **改文件 → `git add` → `git commit` → `git push`**

---

## 1. 确认 git 能用

```powershell
git --version
```

有版本号（比如 `git version 2.47.0.windows.1`）就说明装好了。
报"无法将 git 项识别为..."说明没装，去 <https://git-scm.com/download/win> 装一个，
装完**关掉终端重新打开**（这是最容易忘的一步）。

确认你的身份已经配好：

```powershell
git config --global user.name
git config --global user.email
```

这两个值会写进每一个存档，别人能在 GitHub 上看到是谁提交的。
如果为空，配一下：

```powershell
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

用 GitHub 注册时那个邮箱。

---

## 2. 新手最容易犯的错：在错误的目录里执行命令

**git 命令只对"当前所在目录"生效。** 在 `C:\Windows` 里敲 `git status`，
它只会告诉你"这里不是仓库"，跟你的项目毫无关系。

所以每次开新终端，先确认自己在哪：

```powershell
Get-Location
```

应该看到类似 `D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git`。
不对就换目录：

```powershell
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git'
```

### 2.1 为什么这里不用 `cd`

**你的路径里有 `[TJU]` 这个方括号，而 PowerShell 会把 `[]` 当作通配符**
（`[TJU]` 的意思是"匹配 T、J、U 其中任意一个字母"）。

结果是：**加引号也不行**，`cd` 仍然去做通配符匹配，匹配不到就报错：

```
cd 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT'
→ 找不到路径"D:\2026-2027\[TJU]vibecoding\COLOSTRUCT"，因为该路径不存在。
```

明明路径存在却报"不存在"，就是这个原因——这也是最容易让人怀疑自己的地方。

**解决办法只有一个：用 `Set-Location -LiteralPath`。**
`-LiteralPath` 的意思是"把后面这串字符当作字面路径，不要做任何通配符解释"。

```powershell
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git'
```

平时懒得打这么长，可以自己定义一个缩写，粘一次管一辈子：

```powershell
function cdp { Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git' }
```

以后敲 `cdp` 就是进那个目录。

### 2.2 `cd` 不工作时，按这个顺序排查

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 报"路径不存在"，但你确定它存在 | **路径里有 `[ ]`**（你就是这样） | 改用 `Set-Location -LiteralPath` |
| 报"路径不存在" | 文件夹真的还没建（比如还没 clone） | 先 clone，或 `Get-ChildItem` 看看父目录有什么 |
| 报"路径不存在" | 驱动器和路径拼错、少了一层目录 | `Get-ChildItem` 一层层确认 |
| 报"不是有效的路径" | 用了 cmd 的命令风格（单引号） | 换成 PowerShell，或用双引号 |
| 提示"路径包含非法字符" | 路径里有 `?` `*` `:` 之类 | 检查有没有打错 |
| 敲完没报错，但 `git status` 说不在仓库 | 你进的是仓库**上一级**目录 | 再 `cd` 进一层，或看 `Get-ChildItem` 里有没有 `.git` |
| cmd 里切不到别的盘 | cmd 的 `cd` 默认不换盘 | `cd /d "D:\..."`，或干脆用 PowerShell |

**验证自己在不在对的地方**，最可靠的办法不是看提示符，而是：

```powershell
Get-ChildItem
```

看看列出来的东西是不是你预期的（比如应该有 `.gitignore`、`package.json`）。
看不出来就再敲：

```powershell
git status
```

报"not a git repository"就说明你不在仓库里。

### 2.3 一个绕过目录切换的偷懒办法

`git` 自己支持"在别处执行、指定目标目录"，而且它**不把方括号当通配符**：

```powershell
git -C 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git' status
git -C 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git' log --oneline -5
```

`-C` 后面的路径对 git 来说是普通字符串，所以带 `[TJU]` 也没问题。
不想切目录时可以用这招。

（`npm` 没有等价写法，跑前端还是得先进目录。）

---

## 3. clone：把仓库完整复制到本地（第一次用）

**clone = 下载一份仓库，并且记住它来自哪儿。**

### 3.1 先搞清一件事：你会多出**第二个**文件夹

`git clone` 会**新建一个文件夹**。它不会、也不能塞进你现有的 `Colostruct v3` 里
（因为那个文件夹非空，git 会拒绝）。

所以操作完之后你会有两个文件夹：

```
COLOSTRUCT\
├── Colostruct v3\      ← 你现在这个，继续用来开发、看界面
└── colostruct-git\     ← 新 clone 出来的，专门用来提交上传
```

**为什么要分两个？** 因为你现在的 `Colostruct v3` 里没有 `.git`（不是仓库），
而且混着 `node_modules`（70 MB）。在 clone 出来的干净副本里操作，
才能保证不会误提交那 70 MB，也不会误删队友的文件。

> ⚠️ **`colostruct-git` 这个名字是我随手起的**，不是你的文件夹，也不需要和任何东西对应。
> `git clone` 的第二个参数就是"新文件夹叫什么"，你可以换成任何名字：
> `git clone <地址> 上传用`、`git clone <地址> my-repo` 都行。
> 本文档统一用 `colostruct-git`，你替换成自己用的名字即可。

### 3.2 命令

```powershell
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT'
git clone https://github.com/Qixx-xx/Colostruct.git colostruct-git
```

- 第一条 `Set-Location -LiteralPath`：**先站到父目录**，不要站进已有的项目文件夹里。
  （为什么不用 `cd`：见第 2.1 节，你的路径有方括号。）
- `git clone` 后面第一个参数是仓库地址，第二个是**你希望新建的文件夹名**。
  省略第二个参数时，git 会用仓库名自动命名。
- 执行完会多出一个 `colostruct-git/` 文件夹，里面有完整历史和 `.git`。

**为什么不能直接下载 ZIP？**
ZIP 里没有 `.git`，是一堆"死"的文件。没有历史、不能提交、不能推送。
只有 clone 下来的才是"活"的。

**clone 之后第一件事**：进去看看里面有什么。

```powershell
cd colostruct-git
git ls-files | Select-Object -First 40
```

`git ls-files` 列出"仓库里被跟踪的所有文件"。这比翻文件夹可靠，
因为文件夹里还可能有一堆没被跟踪的临时文件。

---

## 4. 每天最常用的三个查看命令

**改完东西、提交之前，一定要看。** 这一步能避免 90% 的事故。

```powershell
git status
```

回答三个问题：我在哪个分支、改了哪些文件、哪些已经 `add` 了。

输出里的字母含义：

| 符号 | 含义 |
|---|---|
| `M` | 修改过（modified） |
| `A` | 新加的文件（added） |
| `D` | 被删除了（deleted） |
| `R` | 改名/移动（renamed） |
| `??` | 未跟踪的新文件（不是 git 管的） |

```powershell
git diff
```

看**具体改了哪几行**。这是提交前最该看的东西。

```powershell
git log --oneline -10
```

看最近 10 次存档。输出的每一行开头那串 `a1b2c3d` 是这次存档的编号。

---

## 5. 提交的完整流程

### 5.1 挑文件：`git add`

```powershell
git add 具体文件名
```

**强烈建议写具体路径，不要写 `git add -A` 或 `git add .`。**
在多人共享的仓库里，一条 `git add -A` 能把你本机所有乱七八糟的东西都带进去
（包括不该提交的 `node_modules`、`.idea`、别人的临时文件）。

想先看看"如果我 add 会加进去什么"，用**演练模式**：

```powershell
git add --dry-run 前端目录
```

它不真的加，只告诉你结果。这是最有用的一条自查命令。

### 5.2 存档：`git commit`

```powershell
git commit -m "一句话说明这次改了什么"
```

`-m` 后面那句是**存档说明**，写给未来的自己看的。写清楚"做了什么"，
不要写 `update` / `fix` / `改了一下` 这种等于没说的话。

好的例子：
- `feat(frontend): migrate UI from Streamlit to Vue 3`
- `fix(api): return audio_url as absolute URL`

### 5.3 上传：`git push`

```powershell
git push
```

第一次推送新分支时 git 会让你确认，照它给的提示敲就行
（一般是 `git push --set-upstream origin 分支名`）。

**`push` 之前的自查清单：**

- [ ] `git status` 里没有不该提交的文件
- [ ] 没有 `deleted:` 开头的行（除非你真的想删）
- [ ] `git diff` 看过了，改的确实是我想改的

---

## 6. 拉别人的改动：`git pull`

你和队友改同一个仓库，你开始干活前先同步一次：

```powershell
git pull
```

**建议每天开工第一件事就是 `git pull`。** 落后越多，冲突越难处理。

`pull` 可能会做两件事之一：

- 你本地没改过 → 直接把最新的拿下来，无感。
- 你本地也改过，而且改的同一处 → **冲突**，见第 7 节。

---

## 7. 冲突：长什么样，怎么处理

冲突的意思是："这段代码你改了，队友也改了，git 不知道听谁的。"

`git pull` 之后 `git status` 会告诉你哪些文件冲突了（`both modified`）。
打开那个文件，会看到这样的东西：

```
<<<<<<< HEAD
这是你本地的版本
=======
这是队友的版本
>>>>>>> origin/main
```

- `<<<<<<< HEAD` 到 `=======` 之间：**你**的内容
- `=======` 到 `>>>>>>>` 之间：**别人**的内容

**处理办法**（新手版，只做最保守的三件事）：

1. **先问队友。** 这是最省事、最正确的做法。不知道谁对就问问。
2. 想清楚要哪个版本（或者两个都要），**手动编辑这个文件**：
   把 `<<<<<<<` / `=======` / `>>>>>>>` 这三行**连同不要的那部分一起删掉**，
   最后文件里应该只剩正常的代码，一个箭头符号都不留。
3. 告诉 git 已经解决了：

```powershell
git add 那个冲突文件
git commit
```

`commit` 不带 `-m` 时 git 会用默认提示，直接保存退出即可。

> VS Code 会在冲突文件上显示 "Accept Current Change / Accept Incoming Change /
> Accept Both" 几个按钮。**看不懂的时候不要乱点**，先问。

---

## 8. 分支：暂时可以不管，但要知道它是什么

分支 = **同一条时间线上的平行存档**。

- `main`（或 `master`）：主线。**多人项目里通常不直接往这里 push。**
- `feat/xxx`：你自己干活用的分支，干完了再合并回主线。

如果团队走 PR（Pull Request）流程，你的流程会变成：

```powershell
git checkout -b feat/frontend-vue    # 建一个自己的分支
# ...干活、add、commit...
git push -u origin feat/frontend-vue # 推上去
# 然后去 GitHub 网页上点 "Compare & pull request"
```

**不确定团队怎么走，就直接问"我该往哪个分支推、要不要开 PR"。**
推错分支比推不上去麻烦得多。

---

## 9. 六条铁律（新手阶段请严格遵守）

1. **不要在共享分支上 `git push --force`。** 这会覆盖别人的提交，且很难恢复。
2. **不要 `git add -A`。** 明确写路径。
3. **不要提交 `node_modules/`、`dist/`、`.env.local`、`.idea/`。** 见 `FRONTEND_PRIMER.md` 第 7.2 节。
4. **不要直接编辑 `.git/` 里的任何文件。**
5. **`git reset --hard` 之前想清楚。** 它会永久丢弃未提交的改动。
6. **不确定就先 `git status` 和 `git diff`，或者先问。**

---

## 10. 出事了怎么救

按危险程度从低到高：

### 撤销一个文件的修改（没 add 过）

```powershell
git restore 文件名
```

把这个文件恢复到上次存档的样子。**改的东西会没**，所以先确认不要了。

### 撤销 add（加错了）

```powershell
git restore --staged 文件名
```

文件内容不动，只是从"购物车"里拿出来。

### 临时收起来（想切分支但还没改完）

```powershell
git stash        # 把当前改动收进抽屉
git stash pop    # 拿出来
```

### 回到上次存档（会丢弃所有未提交改动）

```powershell
git reset --hard HEAD
```

⚠️ 危险。只在确认改动不要了的时候用。

### 我已经提交错了，但还没 push

```powershell
git commit --amend
```

改掉最近一次提交的说明，或者把刚忘 add 的文件补进去。

### 我以为全毁了

```powershell
git reflog
```

这是"时光机的时光机"，列出了 HEAD 移动过的每一步，包括你以为丢掉的那些。
找到想回去的那一行的编号，然后：

```powershell
git reset --hard 那个编号
```

**`reflog` 是最后的保险。** 只要 `.git` 目录还在，几乎什么都能找回来。

---

## 11. 术语对照表

| 你会看到 | 用大白话理解 |
|---|---|
| 仓库（repository / repo） | 自带时光机的文件夹 |
| `.git/` | 时光机的引擎，别手动改 |
| clone | 完整下载一份仓库（含历史） |
| commit | 存档点 |
| push | 把存档上传到 GitHub |
| pull | 把 GitHub 的新存档下载并合并 |
| fetch | 只下载不合并（一般用不到） |
| branch | 平行时间线 |
| merge | 把两条时间线合起来 |
| conflict | 两边改了同一处，git 不敢替你决定 |
| origin | 远程仓库的默认别名 |
| HEAD | 你当前站的位置 |
| staged | 已经放进"购物车" |
| untracked | 新文件，git 还没开始管 |
| PR（Pull Request） | 在 GitHub 网页上申请"把我的分支合进主线" |

---

## 12. 你这次任务要执行的命令

具体步骤和自查点写在 `FRONTEND_PRIMER.md` 第 7 章，这里只列命令骨架：

```powershell
# 1. 站到父目录（用 -LiteralPath，因为路径里有 [TJU]），clone 出新文件夹
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT'
git clone https://github.com/Qixx-xx/Colostruct.git colostruct-git
Set-Location -LiteralPath 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\colostruct-git'

# 2. 看清仓库现状
git ls-files | Select-Object -First 40

# 3. 打 tag（把旧版钉住）
git tag v1-streamlit-mvp
git push origin v1-streamlit-mvp

# 4. 归档旧代码
git mv app.py legacy_mvp/app.py
git mv ui legacy_mvp/ui
git status

# 5. 拷前端（robocopy 返回 1 是成功）
robocopy 'D:\2026-2027\[TJU]vibecoding\COLOSTRUCT\Colostruct v3\frontend' 'frontend' /E /XD node_modules dist .vite-temp

# 6. 补 .gitignore（用编辑器贴，别覆盖）

# 7. 自查
git add --dry-run frontend | Select-String -Pattern 'node_modules|/dist/|\.idea'
git status

# 8. 提交推送
git add frontend .gitignore
git commit -m "feat(frontend): migrate UI from Streamlit to Vue 3"
git push
```

---

### 12.1 以后怎么办：建议把开发也搬到 clone 里

上面那套"两个文件夹 + 拷来拷去"只适合**这一次**把已有成果上传。

长期建议改成在 `colostruct-git` 里开发：

```powershell
cd colostruct-git\frontend\colostruct_v3
npm install          # 装一次依赖，之后不用再装
npm run dev
```

这样以后改代码就直接 `git add` / `commit` / `push`，不用每次手动拷贝和自查。

`Colostruct v3` 先留着对照几天，确认新位置跑得没问题，就可以删掉或改名成
`Colostruct v3-backup` 存档。**删之前一定确认 `colostruct-git` 里的东西是全的**
（`git status` 干净、`npm run dev` 能起来、界面正常）。

## 13. 一句话总结

**`git status` 看现状 → `git add` 挑文件 → `git commit -m "说明"` 存档 → `git push` 上传。**

拿不准的时候，先 `git status`，再问。

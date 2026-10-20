# Воспроизведение ESP

Для установки использовать готовый payload и [INSTALL.md](../INSTALL.md).
Эта инструкция нужна только для повторного изготовления плагина.

Генератор использует типизированный API Mutagen.Bethesda.Skyrim 0.54.4,
а не запись бинарного формата вручную. Требования: .NET SDK 10,
доступ к NuGet при первом восстановлении пакетов; Python 3.10+
для независимой проверки. Установленная игра не нужна.

Пример из корня репозитория в PowerShell:

```powershell
$root = (Get-Location).Path
$work = Join-Path $root "scratch\0001-shock-nova-neutral-targets"
$project = ".\fixes\0001-shock-nova-neutral-targets\src\generator\ShockNovaPatcher.csproj"
$source = "D:\RFAB\MO2\mods\RFAB\RFAB.esp"
$output = Join-Path $work "candidate\RFAB-ShockNova-NeutralTargets.esp"
dotnet restore $project --locked-mode --packages "$work\nuget" "--property:ArtifactsPath=$work\build"
dotnet build $project --no-restore --configuration Release "--property:ArtifactsPath=$work\build"
dotnet "$work\build\bin\ShockNovaPatcher\release\ShockNovaPatcher.dll" $source $output
python .\fixes\0001-shock-nova-neutral-targets\src\validate_patch.py $source $output
```

Каждая команда должна завершиться успешно до перехода к следующей.
`candidate` должен быть новым каталогом: генератор не перезаписывает
существующий ESP. Для повторного эксперимента выбрать другой выходной
каталог, сохранив имя файла.

После успешной проверки сравнить SHA-256 с `../evidence/build-report.json`.
Для этой исходной базы ожидается:
`640c860aca45858c89946ecc34a92a178022428f8d3e060ced1edc4a68d94994`.
Перенос в payload допустим только после проверки; новый архив создавать
через `tools/fix.py check`, затем `tools/fix.py package`.

На macOS проверены те же `restore`/`build` и запуск сборки через локальный
SDK 10.0.402 в `scratch/0001-shock-nova-neutral-targets/dotnet-sdk/`.
Для NuGet-кеша и результатов сборки использованы игнорируемые каталоги scratch.
`packages.lock.json` фиксирует транзитивные версии и хеши пакетов.

## Что проверяется

- SHA-256 исходной RFAB.esp жёстко закреплён; другая база требует повторной
  диагностики, а не отключения проверки.
- Только MGEF `RFAB.esp:1124AF`, без новых записей.
- UTF-8 исходных FULL/DNAM сохраняется явно; заголовок HEDR 1.7
  берётся от базы, обычный ESP без ESM/ESL-флага.
- Mutagen вычисляет и переиндексирует ссылки на мастера; нет ручного
  изменения байтов ссылок.
- Повторное чтение Mutagen проверяет ключ, мастера и условие.
- `validate_patch.py` независимо сравнивает все исходные поля и ссылки,
  разрешая master-индексы, и допускает только добавленную CTDA.

Исходники специализированного инструмента:
[Mutagen 0.54.4](https://github.com/Mutagen-Modding/Mutagen/tree/0.54.4),
[условие IsHostileToActor](https://github.com/Mutagen-Modding/Mutagen/blob/0.54.4/Mutagen.Bethesda.Skyrim/Records/Common%20Subrecords/IsHostileToActorConditionData_Generated.cs),
[документация override](https://mutagen-modding.github.io/Mutagen/plugins/Create,-Duplicate,-and-Override/).

Формат независимого валидатора сверялся с
[TES5Edit](https://github.com/TES5Edit/TES5Edit/blob/dev-4.1.6/Core/wbDefinitionsTES5.pas).
Ни компиляция генератора, ни валидация ESP не заменяют игровой тест.

# План постоянной установки на текущем Arch Linux

Статус: **шаги1 и2 выполнены пользователем** — локальный пакет установлен,
options сохранены, модуль выгружен и загружен обычным modprobe без явных параметров.
Дисковый и загруженный srcversion A47 совпадают. Полный boot ещё не проверялся.
PM2 успешно пройден: s2idle19:33:35→19:33:40, после resume до finally
manual1/mode2/boost0, затем finally manual0/mode2 и возврат BIOS; оба вентилятора
подтверждены пользователем. Системный шаг выполняет пользователь из своего терминала:
текущая среда агента работает с UID1000 и no-new-privileges, поэтому обычный sudo
в ней не даёт root. Агент не выполнял системных записей и не запускал
`make dkmsinstall`; пользовательский pacman вызвал штатные DKMS hooks.

## Что установлено сейчас

- Ядро и headers: `7.2.9-arch1-1`; имеются dkms3.4.4, base-devel, makepkg и fakeroot.
- Пакет `qc71-laptop-dkms-git r81.ebab4af.p527.20261101-1` владеет
  `/usr/src/qc71_laptop-r81.ebab4af.p527.20261101`; это единственная qc71 версия
  в DKMS и `/usr/src`, installed для7.2.9. Старый source удалён пакетным hook.
- На диске `/lib/modules/7.2.9-arch1-1/updates/dkms/qc71_laptop.ko.zst`
  со srcversion `A47EBF4D6DB5B96BF602F3B`. В памяти после обычного пакетного
  reload также A47. Прежний дисковый модуль1D44 сохранён в backup.
- Пользовательский `qc71_laptop.ko.zst` в репозитории — другой бинарник:
  srcversion `141F63EFD80ADA577A25569`, vermagic `6.11.3-arch1-1`.
  Он сохранён отдельно и не подходит для загрузки на текущем ядре.
- `/etc/modprobe.d/qc71_laptop.conf` содержит
  `options qc71_laptop keyboard_backlight=1 fan_control=1`; modprobe видит
  ровно эту строку options. Другие qc71/TUXEDO/Uniwill overrides и modules-load
  записи при подготовке не находились. TUXEDO/Uniwill модули не загружены.
- У нового `.ko` зависимости `wmi,sparse-keymap,led-class-multicolor`;
  конфиг текущего ядра содержит нужные ACPI/DMI/battery/hwmon/POWER_SUPPLY/LED
  опции. `led_class_multicolor` доступен как модуль. После depmod обычный
  modprobe загрузит зависимости; отдельный modules-load файл для LED не нужен.
- WMI alias уже обеспечивает автозагрузку qc71. В mkinitcpio MODULES толькоi915;
  специальной qc71 записи в initramfs нет.

Pacman hook автоматически пересоздал `/boot/initramfs-linux.img` и завершился
успешно, хотя ручной `mkinitcpio` не запрашивался. Пересозданный образ независимо
проверен через `lsinitcpio -l`: wmi присутствует, qc71/TUXEDO/Uniwill,
led-class-multicolor и sparse-keymap отсутствуют; из локальных modprobe
конфигов включён толькоi915.conf. Preset linux содержит один default образ.
Основания дополнительно выполнять `mkinitcpio -P` сейчас нет: qc71
загружается из основной системы, а новый options файл будет читаться там.
Если состав initramfs к моменту установки изменился, повторить read-only
проверку, прежде чем решать о его пересоздании.

Makefile репозитория и dkms.conf всё ещё используют версию0.0. Не устанавливать
её рядом с пакетной r81. На этой системе Arch hook перечисляет все
`/usr/src/*/dkms.conf`, а не только newest version: две версии одного qc71
могут переустанавливать друг друга при обновлении ядра. Решение — заменить
существующий Arch пакет локальным пакетом с тем же именем, оставив один source.

## Подготовленный bundle

Текущий каталог:

```text
/home/paveliarch/projects/laptop/qc71_laptop/contrib/arch/out/20261101T162640555609Z
```

Внутри:

- `new/qc71-laptop-dkms-git-r81.ebab4af.p527.20261101-1-x86_64.pkg.tar.zst`:
  локальный snapshot текущих C/H/Makefile/LICENSE и отдельный versioned
  dkms.conf. Generated `*.mod.c` и готовые бинарники в source не включены.
- `rollback/qc71-laptop-dkms-git-r81.ebab4af-1-x86_64.pkg.tar.zst`:
  восстановленный пакет из полного установленного source. Это локально
  пересозданный rollback package, не найденный в кэше исходный пакетный архив.
- `backup/old-source`: полная копия установленного `/usr/src` qc71.
- `backup/installed-qc71_laptop.ko.zst`, `user-original-qc71_laptop.ko.zst`,
  `tested-qc71_laptop.ko`: три разных сохранённых бинарника.
- `backup/pacman-info.txt`, `pacman-files.txt`, `dkms-status.txt`, modinfo обоих
  текущих модулей; `backup/config` и `config-inventory.json` сохраняют
  modprobe/modules-load/mkinitcpio/DKMS конфиги и наличие qc71 options файла.
- `source-manifest.json`: точные имена и SHA256 новых исходников, полный
  dkms.conf и srcversion проверенного бинарника; `SHA256SUMS`: контроль bundle.

PKGBUILD из пользовательского qc71 cache не найден. Применена схема из уже
установленного dkms.conf с явными kernel source/build путями. Сетевых source
и новых зависимостей в PKGBUILD нет. Пакет содержит только `/usr/src`, не
переключает fans/LED и не устанавливает modprobe options самостоятельно.

Для повторной подготовки, от обычного пользователя:

```sh
python3 contrib/arch/build-local.py
```

Скрипт создаёт новый каталог, backup и два пакета через makepkg без install.
Штатные DKMS исходники и репозиторный `.ko.zst` не меняет. Он откажет, если
установленная версия изменилась или local `.ko` не совпадает с загруженным
по srcversion. Проверка соответствия архива проверенному бинарнику требует
отдельной сборки из package source, не только этого сравнения бинарников.

Для текущего bundle такая проверка уже выполнена независимым агентом: новый
source из пакета собран в отдельном временном каталоге через
`make -C /lib/modules/7.2.9-arch1-1/build M=<extracted-source> W=1 modules`.
Сборка прошла, modinfo srcversion совпал с проверенной A47 сборкой. Также
проверено точное совпадение new package с manifest/текущими исходниками,
rollback package с полным старым source и все SHA256SUMS. Оба пакета содержат
только `/usr/src`; при этой проверке системная установка не выполнялась.
Последующий результат пользовательской установки приведён ниже. Для вновь
подготовленного bundle проверку соответствия повторить. После уже выполненной
установки guard прежней версии в build-local.py намеренно откажет: для нового
snapshot сначала пересмотреть backup/rollback под изменившийся baseline.

## Шаг 1: установка пакета после успешного PM2 — выполнен

Пользователь выполнил этот шаг: удалена старая DKMS версия, установлена только
`r81.ebab4af.p527.20261101` для7.2.9, на диске A47 и один новый `/usr/src`
source. Строка `CLEAN is deprecated` информационная: сборка, установка,
depmod и автоматический mkinitcpio завершились успешно. Она не требует менять
проверенные исходники или пересобирать пакет сейчас; убрать CLEAN можно при
будущем отдельном изменении packaging. Следующие команды сохранены как
процедура, повторять успешную установку без основания не нужно.

Сначала сохранить **весь bundle** вне временных каталогов и проверить hashes.
Не удалять его при очистке build output. В следующем блоке путь указывает на
уже подготовленный bundle; при новой подготовке использовать новый путь.

```sh
qc71_bundle='/home/paveliarch/projects/laptop/qc71_laptop/contrib/arch/out/20261101T162640555609Z'
cd "$qc71_bundle"
sha256sum --quiet -c SHA256SUMS &&
    sudo pacman -U "$qc71_bundle/new/qc71-laptop-dkms-git-r81.ebab4af.p527.20261101-1-x86_64.pkg.tar.zst"
```

После завершения пакетной операции проверить и передать вывод:

```sh
dkms status -m qc71_laptop
modinfo -n qc71_laptop
modinfo -F srcversion qc71_laptop
ls -d /usr/src/qc71_laptop-*
```

Pacman заменяет старый source пакетным обновлением; Arch hooks снимают старую
DKMS версию и собирают/устанавливают новую для установленных ядер с headers.
Проверить, что в DKMS осталась только версия `r81.ebab4af.p527.20261101`,
для7.2.9 она installed, в `/usr/src` только её source, а на диске srcversion
`A47EBF4D6DB5B96BF602F3B`. Одного успеха pacman
недостаточно: DKMS hook может завершиться с ошибкой. Текущий загруженный
модуль при установке пакета не перезагружается.

**При ошибке hashes, pacman или DKMS, старом srcversion либо лишней версии
остановиться на этом шаге. Не переходить к options/reload до подтверждённой
успешной установки.**

## Шаг 2: options и проверка пакетной загрузки — выполнен

Пользователь подтвердил белую подсветку и обычную работу обоих вентиляторов
после сохранения options, выгрузки и обычного modprobe. Read-only проверка
подтвердила содержимое файла/effective options, memory/diskA47,
keyboard_backlight=Y, fan_control=Y, debugregs=N, manual0/mode2, threshold80,
LEDwhite255/255/255 с configuredbrightness128. PWM127/127, RPM3630/3506
соответствовали текущей автоматической работе BIOS; целевые обороты ими не задавались.

В журнале20:00:47 есть unload и новая успешная загрузка. Отказы необязательных
lightbar/debugfs=-19 ожидаемы при capabilitylightbar0 и debugregs=N. Ошибок
инициализации keyboard LED или EC transport в этом фрагменте нет. Около reload
виден неизвестный event187; его семантика не назначалась и обработчик не менялся.
Debugfs не инициализирован: параметрN и init-19 согласуются с code guard до
создания каталога. Это не вывод из Path.exists под UID1000: EACCES родительского
каталога мог бы дать ложный False. Следующая команда — запись выполненной
процедуры, повторять её не нужно:

Этот шаг выполнялся отдельно после проверки результатов шага1.
Начать из подтверждённого manual0/mode2. Команда сохраняет проверенные opt-in
интерфейсы и выполняет обычную пакетную перезагрузку модуля:

```sh
sudo sh -c 'umask 022; set -C; printf "%s\n" "options qc71_laptop keyboard_backlight=1 fan_control=1" > /etc/modprobe.d/qc71_laptop.conf' &&
    sudo modprobe -r qc71_laptop &&
    test ! -d /sys/module/qc71_laptop &&
    sudo modprobe qc71_laptop
```

До первого выполнения файл отсутствовал; теперь он создан. **Перед новым
созданием существующий файл нужно сравнить с backup и сохранить новые настройки,
а не перезаписывать.** Режим `set -C` откажет при существующем обычном файле,
не перезаписывая его. Цепочка `&&` не продолжит reload после отказа создания
файла или выгрузки. Debugregs оставлен выключенным
по умолчанию; постоянный root-write доступ к EC для обычной работы не нужен.
Fan opt-in только открывает интерфейс, автоматический BIOS режим сохраняется.

Если создание options или выгрузка не удались, остановиться, не переходя к
следующей команде. `modprobe` здесь без явных параметров: проверяется файл
настроек, а не повторная insmod из workspace. После неё нужны srcversion/parameters, LED sysfs,
manual0/mode2, threshold80 и журнал без ошибок; цвет/яркость оцениваются после
обычной клавиши встроенной клавиатуры. Ожидаются keyboard_backlight=Y,
fan_control=Y, debugregs=N; отсутствие raw debugfs после закрытия debugregs
ожидаемо. Runtime reload не подменяет отдельное наблюдение следующего полного boot.

## Откат

Rollback package восстанавливает прежнее владение source и пересобирает его
через те же DKMS hooks. До отката вернуть управление BIOS, если был manual
режим. Новые параметры нельзя оставлять старому модулю: он их не понимает.
Для текущего baseline qc71 options файл до установки отсутствовал:

```sh
sudo rm /etc/modprobe.d/qc71_laptop.conf
sudo pacman -U "$qc71_bundle/rollback/qc71-laptop-dkms-git-r81.ebab4af-1-x86_64.pkg.tar.zst"
dkms status -m qc71_laptop
modinfo -F srcversion qc71_laptop
```

Если options файл существовал на момент фактического backup, вместо удаления
восстановить его точную копию из `backup/config`. Не копировать все сохранённые
системные конфиги поверх текущих без сравнения: меняется только добавленный
qc71 файл. Переключение уже загруженного модуля на rollback выполнить отдельно
после BIOS handoff; установка пакета сама это не делает.

Если DKMS пересборка старого source не удалась, сохранённый installed бинарник
подходит только для7.2.9. Его явное восстановление в исходный путь с depmod —
отдельный аварийный шаг, а не замена штатному пакетному откату. Пользовательский
бинарник6.11.3 не загружать принудительно на7.2.9.

Локальные исправления нужно сохранять при будущих обновлениях AUR/upstream;
пересборка обычного upstream checkout поверх этого пакета их не переносит.

import QtQuick 2.9
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import io.thp.pyotherside 1.5
import QtSystemInfo 5.5

MainView {
    id: root
    objectName: "mainView"
    applicationName: "soundtype.n0madd3v0ps"
    automaticOrientation: true
    width: units.gu(45)
    height: units.gu(78)

    property bool recording: false

    // не гасить экран, пока идёт запись (issue #5)
    ScreenSaver { screenSaverEnabled: !root.recording }
    property bool ready: false
    property string statusText: "Загрузка движка…"
    property real level: 0.0
    property bool transcribing: false
    property real elapsed: 0
    property string progressText: ""
    property string partialText: ""
    property bool autoCopy: true
    property string activeModel: "parakeet"
    property bool modelSwitchBusy: false
    property real retryTs: 0
    property bool depsMissing: false
    property bool downloading: false
    property string downloadStage: ""
    property int downloadPct: -1
    property string downloadError: ""

    function mmss(s) {
        var m = Math.floor(s / 60);
        var r = Math.floor(s % 60);
        return m + ":" + (r < 10 ? "0" + r : r);
    }

    function appendText(chunk) {
        if (!chunk)
            return;
        var body = transcript.text;
        if (body.length > 0 && !/\s$/.test(body))
            body += " ";
        transcript.text = body + chunk;
        transcript.cursorPosition = transcript.text.length;
    }

    // Копирование через скрытое поле: TextEdit.copy() кладёт текст в буфер
    // системы, отдельного API для этого в конфайнменте нет.
    function copyText(s) {
        if (!s || !s.length)
            return false;
        clipboardHelper.text = s;
        clipboardHelper.selectAll();
        clipboardHelper.copy();
        clipboardHelper.deselect();
        return true;
    }

    function copyAll() {
        if (root.copyText(transcript.text))
            toast.show("Скопировано в буфер обмена");
    }

    TextEdit {
        id: clipboardHelper
        visible: false
        width: 0
        height: 0
    }

    Python {
        id: py

        Component.onCompleted: {
            addImportPath(Qt.resolvedUrl("../py"));

            setHandler("status", function (s) {
                root.statusText = "Загрузка модели…";
            });
            setHandler("deps-missing", function (what) {
                root.depsMissing = true;
                root.statusText = "Нужно скачать модель";
            });
            setHandler("download-progress", function (stage, pct) {
                root.downloading = true;
                root.downloadError = "";
                root.downloadStage = stage;
                root.downloadPct = pct;
            });
            setHandler("download-done", function () {
                root.downloading = false;
                root.depsMissing = false;
                root.statusText = "Загрузка движка…";
            });
            setHandler("download-error", function (msg) {
                root.downloading = false;
                root.downloadError = msg;
                root.statusText = "Ошибка загрузки";
            });
            setHandler("ready", function (name) {
                root.ready = true;
                root.statusText = "Готово — нажми микрофон";
            });
            setHandler("elapsed", function (sec) {
                root.elapsed = sec;
                if (root.recording)
                    root.statusText = "Пишу… " + root.mmss(sec);
            });
            setHandler("recording", function (on) {
                root.recording = on;
                if (on) {
                    root.elapsed = 0;
                    root.statusText = "Пишу… 0:00";
                    root.partialText = "";
                    waveform.bars = new Array(waveform.count).fill(0);
                } else {
                    root.level = 0.0;
                }
            });
            setHandler("transcribing", function (on) {
                root.transcribing = on;
                if (on)
                    root.statusText = "Расшифровываю…";
                else
                    root.progressText = "";
            });
            setHandler("progress", function (idx, total) {
                root.progressText = idx + "/" + total;
                root.statusText = total > 1
                    ? "Расшифровываю… " + idx + " из " + total
                    : "Расшифровываю…";
            });
            setHandler("partial", function (idx, t) {
                root.partialText += t;
            });
            setHandler("final", function (t, ts) {
                root.appendText(t);
            });
            // Повторное распознавание записи из истории.
            setHandler("retried", function (ts, t) {
                root.retryTs = 0;
                if (!t || !t.length) {
                    toast.show("Снова ничего не распозналось");
                    return;
                }
                historyPage.applyRetry(ts, t);
                if (root.copyText(t))
                    toast.show("Готово — новый текст в буфере");
            });
            // Расшифровка закончена: кладём текст в буфер, чтобы можно
            // было сразу вернуться в другое приложение и вставить.
            setHandler("done", function (t) {
                root.partialText = "";
                root.statusText = root.ready ? "Готово — нажми микрофон"
                                             : root.statusText;
                if (!t || !t.length) {
                    toast.show("Ничего не распознано");
                    return;
                }
                if (root.autoCopy && root.copyText(t))
                    toast.show("Скопировано — можно вставлять");
            });
            setHandler("level", function (v) {
                root.level = v;
                if (root.recording)
                    waveform.push(v);
            });
            setHandler("error", function (msg) {
                root.statusText = "Ошибка: " + msg;
                toast.show(msg);
            });
            setHandler("model", function (name) {
                root.activeModel = name;
                root.modelSwitchBusy = false;
                // движок только что выгружен (смена профиля) либо ещё не
                // загружен (старт) — микрофон разблокирует событие 'ready'
                root.ready = false;
            });

            importModule("backend", function () {
                call("backend.init", []);
            });
        }

        onError: {
            root.statusText = "Сбой Python";
            console.log("pyotherside error: " + traceback);
        }
    }

    ListModel { id: historyModel }

    PageStack {
        id: stack
        anchors.fill: parent
        Component.onCompleted: push(mainPage)

        // ------------------------------------------ главный экран

        Page {
            id: mainPage

            header: PageHeader {
                id: pageHeader
                title: "SoundType"
                subtitle: root.statusText
                trailingActionBar.actions: [
                    Action {
                        iconName: "edit-copy"
                        text: "Копировать"
                        enabled: transcript.text.length > 0
                        onTriggered: root.copyAll()
                    },
                    Action {
                        iconName: "edit-clear"
                        text: "Очистить"
                        enabled: transcript.text.length > 0
                        onTriggered: transcript.text = ""
                    },
                    Action {
                        iconName: "history"
                        text: "История"
                        onTriggered: stack.push(historyPage)
                    }
                ]
            }

            ColumnLayout {
                anchors {
                    top: pageHeader.bottom
                    left: parent.left
                    right: parent.right
                    bottom: parent.bottom
                    margins: units.gu(2)
                }
                spacing: units.gu(2)

                // ---------- расшифровка ----------
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: units.gu(1)
                    color: theme.palette.normal.field
                    border.width: units.dp(1)
                    border.color: theme.palette.normal.base

                    Flickable {
                        id: flick
                        anchors.fill: parent
                        anchors.margins: units.gu(1.5)
                        contentHeight: textColumn.height
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        Column {
                            id: textColumn
                            width: flick.width
                            spacing: units.gu(0.5)

                            TextEdit {
                                id: transcript
                                width: parent.width
                                wrapMode: TextEdit.Wrap
                                selectByMouse: true
                                font.pixelSize: units.gu(2.2)
                                color: theme.palette.normal.fieldText
                                selectionColor: LomiriColors.orange
                                onTextChanged: flick.contentY = Math.max(0, textColumn.height - flick.height)
                            }

                            Label {
                                id: partialLabel
                                width: parent.width
                                wrapMode: Text.Wrap
                                font.pixelSize: units.gu(2.2)
                                font.italic: true
                                opacity: 0.55
                                color: theme.palette.normal.fieldText
                                text: {
                                    if (root.partialText.length)
                                        return root.partialText;
                                    return root.transcribing
                                          ? ("расшифровываю… " + root.progressText)
                                          : "";
                                }
                            }
                        }
                    }

                    Label {
                        anchors.centerIn: parent
                        width: parent.width - units.gu(6)
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        opacity: 0.4
                        text: "Нажми микрофон и говори.\nТекст можно править прямо здесь."
                        visible: transcript.text.length === 0 && partialLabel.text.length === 0
                    }
                }

                // ---------- голосовые волны ----------
                Item {
                    id: waveform
                    Layout.fillWidth: true
                    Layout.preferredHeight: units.gu(6)
                    visible: root.recording

                    property int count: 40
                    property var bars: []

                    function push(v) {
                        var a = bars.slice(1);
                        a.push(v);
                        bars = a;
                    }

                    Row {
                        anchors.centerIn: parent
                        spacing: units.dp(3)
                        Repeater {
                            model: waveform.count
                            Rectangle {
                                property real v: index < waveform.bars.length
                                                 ? waveform.bars[index] : 0
                                width: units.dp(4)
                                height: units.dp(3)
                                       + v * (waveform.height - units.dp(3))
                                radius: width / 2
                                color: LomiriColors.orange
                                anchors.verticalCenter: parent.verticalCenter
                                Behavior on height {
                                    NumberAnimation { duration: 110 }
                                }
                            }
                        }
                    }
                }

                // ---------- авто-копирование ----------
                RowLayout {
                    Layout.fillWidth: true
                    spacing: units.gu(1)

                    Switch {
                        id: autoCopySwitch
                        checked: root.autoCopy
                        onCheckedChanged: root.autoCopy = checked
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "Копировать в буфер после остановки"
                        wrapMode: Text.Wrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                // ---------- модель распознавания ----------
                Label {
                    text: "Модель распознавания"
                    fontSize: "small"
                    color: theme.palette.normal.backgroundSecondaryText
                }
                OptionSelector {
                    id: modelSelector
                    Layout.fillWidth: true
                    model: ["Мультиязычная (Parakeet v3)",
                            "Русская (GigaAM-v3)"]
                    enabled: !root.modelSwitchBusy && !root.recording && !root.transcribing
                    selectedIndex: root.activeModel === "gigaam" ? 1 : 0
                    onDelegateClicked: function (index) {
                        var name = index === 1 ? "gigaam" : "parakeet";
                        if (name === root.activeModel)
                            return;
                        root.modelSwitchBusy = true;
                        py.call("backend.set_model", [name]);
                    }
                }
                Label {
                    visible: root.activeModel === "gigaam"
                    text: "Русский профиль: пунктуация и ё из коробки"
                    fontSize: "x-small"
                    color: theme.palette.normal.backgroundTertiaryText
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

                // ---------- кнопка записи ----------
                Item {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: units.gu(15)
                    Layout.preferredHeight: units.gu(15)

                    // кольцо громкости
                    Rectangle {
                        anchors.centerIn: parent
                        width: units.gu(10) + units.gu(5) * root.level
                        height: width
                        radius: width / 2
                        color: LomiriColors.orange
                        opacity: root.recording ? 0.22 : 0
                        Behavior on width { NumberAnimation { duration: 90 } }
                        Behavior on opacity { NumberAnimation { duration: 180 } }
                    }

                    Rectangle {
                        id: micButton
                        anchors.centerIn: parent
                        width: units.gu(10)
                        height: width
                        radius: width / 2
                        enabled: root.ready && !root.transcribing
                        opacity: (root.ready && !root.transcribing) ? 1 : 0.4
                        color: root.recording ? LomiriColors.red : LomiriColors.green
                        Behavior on color { ColorAnimation { duration: 180 } }

                        Icon {
                            anchors.centerIn: parent
                            width: units.gu(4.5)
                            height: width
                            name: root.recording ? "media-playback-stop" : "audio-input-microphone-symbolic"
                            color: "white"
                        }

                        MouseArea {
                            anchors.fill: parent
                            enabled: root.ready && !root.transcribing
                            onClicked: {
                                if (root.recording) {
                                    py.call("backend.stop", []);
                                } else {
                                    // Начинаем с чистого листа: прошлая
                                    // расшифровка уже лежит в истории.
                                    transcript.text = "";
                                    py.call("backend.start", []);
                                }
                            }
                        }
                    }
                }
            }

            // Первый запуск: модели ещё нет — предлагаем скачать.
            Rectangle {
                anchors {
                    top: pageHeader.bottom
                    left: parent.left
                    right: parent.right
                    bottom: parent.bottom
                }
                color: theme.palette.normal.background
                visible: root.depsMissing
                z: 50

                MouseArea {
                    // Перехватываем тапы, чтобы они не проваливались на
                    // транскрипт/клавиатуру под оверлеем, пока идёт первый
                    // запуск без скачанной модели.
                    anchors.fill: parent
                }

                Column {
                    anchors.centerIn: parent
                    width: parent.width - units.gu(6)
                    spacing: units.gu(2)

                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: units.gu(6)
                        height: width
                        name: "save-to"
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: "Для работы нужно скачать модель распознавания "
                              + "(около 500 МБ). Лучше делать это по Wi-Fi.\n"
                              + "После загрузки приложение работает полностью офлайн."
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        color: LomiriColors.red
                        visible: root.downloadError.length > 0
                        text: root.downloadError
                    }
                    ProgressBar {
                        width: parent.width
                        visible: root.downloading
                        indeterminate: root.downloadPct < 0
                        minimumValue: 0
                        maximumValue: 100
                        value: root.downloadPct
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        visible: root.downloading
                        textSize: Label.Small
                        opacity: 0.7
                        text: root.downloadStage
                              + (root.downloadPct >= 0
                                 ? "  " + root.downloadPct + "%" : "")
                    }
                    Button {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: !root.downloading
                        color: LomiriColors.green
                        text: root.downloadError.length ? "Повторить" : "Скачать"
                        onClicked: py.call("backend.fetch_deps", [])
                    }
                }
            }
        }

        // ------------------------------------------ экран истории

        Page {
            id: historyPage
            visible: false

            property bool loaded: false

            function reload() {
                historyModel.clear();
                py.call("backend.history_list", [], function (items) {
                    for (var i = 0; i < items.length; i++)
                        historyModel.append({
                            "when": items[i].when,
                            "body": items[i].text,
                            "ts": items[i].ts,
                            "hasAudio": items[i].has_audio
                        });
                    historyPage.loaded = true;
                });
            }

            // Обновляем строку на месте, чтобы не перерисовывать весь список
            // и не терять положение прокрутки.
            function applyRetry(ts, text) {
                for (var i = 0; i < historyModel.count; i++) {
                    if (Math.abs(historyModel.get(i).ts - ts) < 0.001) {
                        if (text && text.length)
                            historyModel.setProperty(i, "body", text);
                        return;
                    }
                }
            }

            onVisibleChanged: if (visible) reload()

            header: PageHeader {
                id: historyHeader
                title: "История"
                subtitle: historyModel.count + " записей"
                trailingActionBar.actions: [
                    Action {
                        iconName: "delete"
                        text: "Очистить всё"
                        enabled: historyModel.count > 0
                        onTriggered: py.call("backend.history_clear", [], function () {
                            historyPage.reload();
                            toast.show("История очищена");
                        })
                    }
                ]
            }

            ListView {
                anchors {
                    top: historyHeader.bottom
                    left: parent.left
                    right: parent.right
                    bottom: parent.bottom
                }
                clip: true
                model: historyModel

                delegate: ListItem {
                    id: row
                    height: entry.height + units.gu(2)

                    Column {
                        id: entry
                        anchors {
                            left: parent.left
                            right: retryButton.visible ? retryButton.left : parent.right
                            verticalCenter: parent.verticalCenter
                            leftMargin: units.gu(2)
                            rightMargin: units.gu(1.5)
                        }
                        spacing: units.gu(0.5)

                        Label {
                            width: parent.width
                            text: model.body
                            wrapMode: Text.Wrap
                            maximumLineCount: 6
                            elide: Text.ElideRight
                        }
                        Label {
                            text: model.when + (model.hasAudio ? "" : " · запись не сохранилась")
                            textSize: Label.Small
                            opacity: 0.5
                        }
                    }

                    // Переспросить модель. Есть только у записей, для которых
                    // ещё сохранён звук — иначе распознавать нечего.
                    AbstractButton {
                        id: retryButton
                        visible: model.hasAudio
                        enabled: !root.transcribing
                        width: units.gu(5)
                        height: units.gu(5)
                        anchors {
                            right: parent.right
                            rightMargin: units.gu(1)
                            verticalCenter: parent.verticalCenter
                        }

                        Icon {
                            anchors.centerIn: parent
                            width: units.gu(2.5)
                            height: width
                            name: "reload"
                            color: theme.palette.normal.backgroundText
                            opacity: (root.transcribing && root.retryTs === model.ts) ? 0.3
                                   : (retryButton.enabled ? 0.8 : 0.3)
                        }

                        onClicked: {
                            root.retryTs = model.ts;
                            py.call("backend.retry", [model.ts]);
                            toast.show("Распознаю заново…");
                        }
                    }

                    onClicked: {
                        if (root.copyText(model.body))
                            toast.show("Скопировано в буфер обмена");
                    }
                }

                Label {
                    anchors.centerIn: parent
                    width: parent.width - units.gu(8)
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    opacity: 0.4
                    text: "Пока пусто.\nВсё, что распознается, сохраняется сюда."
                    visible: historyModel.count === 0 && historyPage.loaded
                }
            }
        }
    }

    // ---------- всплывающее уведомление (поверх обоих экранов) ----------
    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: units.gu(4)
        width: Math.min(parent.width - units.gu(6), toastLabel.implicitWidth + units.gu(4))
        height: toastLabel.implicitHeight + units.gu(2)
        radius: units.gu(0.8)
        color: theme.palette.normal.overlay
        border.width: units.dp(1)
        border.color: theme.palette.normal.base
        opacity: 0
        z: 100

        function show(msg) {
            toastLabel.text = msg;
            toastAnim.restart();
        }

        Label {
            id: toastLabel
            anchors.centerIn: parent
            width: toast.width - units.gu(4)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }

        SequentialAnimation {
            id: toastAnim
            NumberAnimation { target: toast; property: "opacity"; to: 1; duration: 150 }
            PauseAnimation { duration: 1600 }
            NumberAnimation { target: toast; property: "opacity"; to: 0; duration: 400 }
        }
    }
}

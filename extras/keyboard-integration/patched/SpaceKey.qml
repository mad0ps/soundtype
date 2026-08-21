/*
 * Copyright 2013 Canonical Ltd.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation; version 3.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

import QtQuick 2.4
import Lomiri.Components 1.3

import "key_constants.js" as UI
import "languages.js" as Languages

ActionKey {
    label: " ";
    shifted: " ";

    normalColor: fullScreenItem.theme.charKeyColor
    pressedColor: fullScreenItem.theme.charKeyPressedColor

    action: "space"
    switchBackFromSymbols: true

    overridePressArea: true

    Label {
        id: langLabel
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -parent.rowMargin / 2 - units.gu(0.15)
        font.family: UI.fontFamily
        font.weight: Font.Light
        font.pixelSize: parent.fontSize * 0.6
        text: Languages.languageIdToName(maliit_input_method.activeLanguage)
        horizontalAlignment: Text.AlignHCenter
        visible: !panel.hideKeyLabels
        // на время диктовки пробел отдан волне
        opacity: spaceWave.visible ? 0.12 : UI.spaceOpacity
    }

    // SoundType: индикатор диктовки в левой части пробела (справа его
    // закрывает палец при холде); серый = движок не в памяти, зелёный =
    // готов (движок загружен), красный пульс = запись, жёлтый = занят
    // (загрузка движка или расшифровка)
    Icon {
        id: micIndicator
        name: "audio-input-microphone-symbolic"
        width: units.gu(2.6)
        height: width
        anchors.verticalCenter: langLabel.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: units.gu(1)
        visible: !panel.hideKeyLabels
        color: fullScreenItem.dictationStatus === "recording" ? "red"
             : fullScreenItem.dictationStatus === "processing" ? "gold"
             : fullScreenItem.dictationStatus === "ready" ? "limegreen"
             : "gray"
        opacity: 0.9
    }

    // SoundType: волна-история — непрерывный конвейер. Высоты баров не
    // анимируются: лента физически ползёт влево с постоянной скоростью
    // (линейный слайд на 4 шага за период замера, 32 бара/сек), новые бары
    // заезжают из-за правого края под клипом. Так нет степ-энд-гоу.
    Item {
        id: spaceWave
        clip: true
        anchors.verticalCenter: micIndicator.verticalCenter
        anchors.left: micIndicator.right
        anchors.leftMargin: units.gu(0.8)
        anchors.right: parent.right
        anchors.rightMargin: units.gu(1)
        height: units.gu(2.2)
        visible: micIndicator.visible
                 && (fullScreenItem.dictationStatus === "recording"
                     || fullScreenItem.dictationStatus === "processing")

        property real step: units.gu(1.15)
        property int bars: Math.max(8, Math.floor(width / step) + 8)
        property real slide: 0
        // скорость ленты, px/с: 3 шага за номинальный период замера 125 мс
        property real beltSpeed: 3 * step / 0.125

        // Замеры приходят с джиттером (аудио-цикл + D-Bus). Сброс к
        // фиксированному отступу давал рывок; вместо этого остаток пути
        // НАКАПЛИВАЕТСЯ, а длительность анимации считается из постоянной
        // скорости — лента едет ровно при любом дрожании таймингов.
        Connections {
            target: fullScreenItem
            onDictationWaveChanged: {
                waveSlideAnim.stop();
                var s = spaceWave.slide + 3 * spaceWave.step;
                var cap = 6 * spaceWave.step;
                if (s > cap) s = cap;   // не даём очереди разгоняться
                spaceWave.slide = s;
                waveSlideAnim.duration = 1000 * s / spaceWave.beltSpeed;
                waveSlideAnim.restart();
            }
        }

        NumberAnimation {
            id: waveSlideAnim
            target: spaceWave
            property: "slide"
            to: 0
            easing.type: Easing.Linear
        }

        Row {
            id: waveRow
            spacing: units.gu(0.7)
            x: spaceWave.width - width + spaceWave.slide
            anchors.verticalCenter: parent.verticalCenter

            Repeater {
                model: spaceWave.bars
                delegate: Item {
                    width: units.gu(0.45)
                    height: units.gu(2.2)
                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.width
                        radius: width / 2
                        antialiasing: true
                        color: fullScreenItem.dictationMicSilent ? "gray"
                             : fullScreenItem.dictationStatus === "processing" ? "gold"
                             : "red"
                        height: {
                            var arr = fullScreenItem.dictationWave;
                            var i = arr.length - spaceWave.bars + index;
                            var v = i >= 0 ? arr[i] : 0.0;
                            // минимум = ширина бара: в тишине идеальный кружок
                            return Math.max(parent.width,
                                            parent.height * Math.min(1.0, v));
                        }
                    }
                }
            }
        }
    }

    MouseArea {
        id: swipeArea
        anchors.fill: parent

        // SoundType hold-space: после pressAndHold решение откладывается —
        // движение пальца = тачпад (как в стоке), отпускание без движения =
        // toggle диктовки.
        property bool holdArmed: false
        property real holdX: 0
        property real holdY: 0

        function enterCursorSwipe(mx, my) {
            holdArmed = false
            fullScreenItem.prevSwipePositionX = mx
            fullScreenItem.prevSwipePositionY = my
            fullScreenItem.cursorSwipe = true
            spaceKey.currentlyPressed = false
        }

        onPressAndHold: {
            holdArmed = true
            holdX = mouseX
            holdY = mouseY
            fullScreenItem.dictationHoldFeedback()
        }

        onPressed: {
            fullScreenItem.keyFeedback();
            spaceKey.currentlyPressed = true
            fullScreenItem.timerSwipe.stop()
        }
        onReleased: {
            if (holdArmed) {
                holdArmed = false
                spaceKey.currentlyPressed = false
                fullScreenItem.toggleDictation()
                return
            }
            if (fullScreenItem.cursorSwipe) {
                fullScreenItem.timerSwipe.restart()
            } else if (fullScreenItem.dictationStatus === "recording") {
                // короткий тап во время записи = стоп диктовки, пробел не печатаем
                spaceKey.currentlyPressed = false
                fullScreenItem.toggleDictation()
            } else {
                spaceKey.currentlyPressed = false
                event_handler.onKeyReleased("", "space")
                if (switchBackFromSymbols && panel.state === "SYMBOLS") {
                    panel.state = "CHARACTERS"
                }
            }
        }

        onMouseXChanged: {
            if (holdArmed && (Math.abs(mouseX - holdX) > units.gu(1) || Math.abs(mouseY - holdY) > units.gu(1))) {
                enterCursorSwipe(mouseX, mouseY)
            }
            if (fullScreenItem.cursorSwipe) {
                fullScreenItem.processSwipe(mouseX, mouseY);
            }
        }

        onMouseYChanged: {
            if (holdArmed && (Math.abs(mouseX - holdX) > units.gu(1) || Math.abs(mouseY - holdY) > units.gu(1))) {
                enterCursorSwipe(mouseX, mouseY)
            }
            if (fullScreenItem.cursorSwipe) {
                fullScreenItem.processSwipe(mouseX, mouseY);
            }
        }
    }

}

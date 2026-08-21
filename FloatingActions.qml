import QtQuick 2.9
import Lomiri.Components 1.3
import QtQuick.Layouts 1.3
import io.thp.pyotherside 1.5
import "keys/"

RowLayout {
    id: root

    readonly property bool isWide: width > units.gu(60)

    anchors {
        top: parent.top
        left: parent.left
        right: parent.right
        margins: units.gu(1)
        topMargin: toolbar.height + units.gu(1)
    }

    Python {
        id: python
        Component.onCompleted: {
            addImportPath('/home/phablet/soundtype/py');
            setHandler('statusChanged', function(newStatus) {
                dictationButton.status = newStatus;
                if (newStatus === "recording" || newStatus === "processing") {
                    fullScreenItem.timerSwipe.stop();
                } else {
                    fullScreenItem.timerSwipe.restart();
                }
            });
            setHandler('partialReady', function(text) {
                // фраза распозналась — печатаем сразу, пока идёт запись
                if (text !== "") {
                    event_handler.onKeyReleased(text + " ");
                }
            });
            setHandler('transcriptionReady', function(text) {
                // весь текст уже напечатан фразами — только закрываем меню
                fullScreenItem.exitSwipeMode();
            });
            importModule('soundtype_dbus_listener', function() {
                python.call('soundtype_dbus_listener.init', []);
            });
        }
    }

    FloatingActionKey {
        id: startLineButton

        Layout.alignment: Qt.AlignLeft
        Layout.preferredWidth: units.gu(5)
        Layout.preferredHeight: units.gu(5)
        action: Action {
            iconName: "go-first"
            onTriggered: {
                if (cursorSwipeArea.selectionMode) {
                    fullScreenItem.selectStartOfLine();
                } else {
                    fullScreenItem.moveToStartOfLine();
                }
            }
        }
    }

    FloatingActionKey {
        id: startDocButton

        iconRotation: 90
        Layout.alignment: Qt.AlignLeft
        Layout.preferredWidth: units.gu(5)
        Layout.preferredHeight: units.gu(5)
        action: Action {
            iconName: "go-first"
            onTriggered: {
                if (cursorSwipeArea.selectionMode) {
                    fullScreenItem.selectStartOfDocument();
                } else {
                    fullScreenItem.moveToStartOfDocument();
                }
            }
        }
    }

    FloatingActionKey {
        id: doneButton

        Layout.alignment: root.isWide ? Qt.AlignLeft : Qt.AlignHCenter
        Layout.fillWidth: root.isWide ? false : true
        Layout.minimumWidth: units.gu(5)
        Layout.preferredWidth: units.gu(7)
        Layout.preferredHeight: units.gu(5)
        keyFeedback: false
        action: Action {
            iconName: "input-keyboard-symbolic"
            onTriggered: {
                fullScreenItem.exitSwipeMode()
            }
        }
    }

    FloatingActionKey {
        id: dictationButton

        property string status: "ready"

        Layout.alignment: root.isWide ? Qt.AlignLeft : Qt.AlignHCenter
        Layout.minimumWidth: units.gu(5)
        Layout.preferredWidth: units.gu(7)
        Layout.preferredHeight: units.gu(5)
        
        Rectangle {
            anchors.fill: parent
            color: dictationButton.status === "recording" ? "red" : (dictationButton.status === "processing" ? "orange" : "transparent")
            opacity: 0.3
            radius: units.gu(0.5)
        }

        action: Action {
            iconName: "audio-input-microphone-symbolic"
            onTriggered: {
                fullScreenItem.timerSwipe.stop();
                python.call('soundtype_dbus_listener.toggle_dictation', []);
            }
        }
    }

    // Spacer
    Item {
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: true
        visible: root.isWide
    }

    FloatingActionKey {
        id: rightDoneButton

        Layout.alignment: Qt.AlignRight
        Layout.minimumWidth: units.gu(5)
        Layout.preferredWidth: units.gu(7)
        Layout.preferredHeight: units.gu(5)
        visible: root.isWide
        keyFeedback: false
        action: Action {
            iconName: "input-keyboard-symbolic"
            onTriggered: {
                fullScreenItem.exitSwipeMode()
            }
        }
    }

    FloatingActionKey {
        id: endDocButton

        iconRotation: 90
        Layout.alignment: Qt.AlignRight
        Layout.preferredWidth: units.gu(5)
        Layout.preferredHeight: units.gu(5)
        action: Action {
            iconName: "go-last"
            onTriggered: {
                if (cursorSwipeArea.selectionMode) {
                    fullScreenItem.selectEndOfDocument();
                } else {
                    fullScreenItem.moveToEndOfDocument();
                }
            }
        }
    }

    FloatingActionKey {
        id: endLineButton

        Layout.alignment: Qt.AlignRight
        Layout.preferredWidth: units.gu(5)
        Layout.preferredHeight: units.gu(5)
        action: Action {
            iconName: "go-last"
            onTriggered: {
                if (cursorSwipeArea.selectionMode) {
                    fullScreenItem.selectEndOfLine();
                } else {
                    fullScreenItem.moveToEndOfLine();
                }
            }
        }
    }
}

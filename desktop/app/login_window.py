import re

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import theme
from app.api_client import ApiClient
from app.auth_rules import (
    DEFAULT_POLICY,
    has_special,
    has_uppercase,
    load_policy,
    login_problems,
    registration_problems,
)
from app.i18n import describe_error, language, set_language, tr
from app.widgets import Alert, Segmented, button, label
from app.worker import run_task


class LoginWindow(QDialog):
    """Login / registration. On success self.api holds an authenticated ApiClient."""

    def __init__(self, api_url: str, parent=None):
        super().__init__(parent)
        self.settings = QSettings("MiniDrive", "Desktop")
        # internal configuration (app/config.py); never shown to the user
        self.api_url = api_url
        self.api: ApiClient | None = None
        self.mode = "login"
        self.setMinimumSize(980, 640)
        self.resize(1060, 680)
        self.values = {"identifier": self.settings.value("identifier", "")}
        self.policy = dict(DEFAULT_POLICY)
        self.password_hint = None
        self.password_rules = None
        self.password_edit = self.email_edit = self.username_edit = None
        self.availability_labels: dict[str, QLabel] = {}
        self.availability: dict[str, str | None] = {"email": None, "username": None}
        # one debounced server check per field while the user types
        self.availability_timers: dict[str, QTimer] = {}
        for field in ("email", "username"):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(450)
            timer.timeout.connect(lambda f=field: self._check_availability(f))
            self.availability_timers[field] = timer
        # the form rules come from the server (password length, username format)
        run_task(load_policy, ApiClient(api_url), on_success=self._policy_loaded)
        self.root = QHBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)
        self.build()

    # --- construction (rebuilt when the language changes) ------------------------------

    def _remember_inputs(self) -> None:
        for key in ("identifier", "email", "username", "display_name"):
            widget = getattr(self, f"{key}_edit", None)
            if widget is not None:
                self.values[key] = widget.text()

    def build(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.setWindowTitle(f"{tr('app.name')}: {tr('auth.action.login' if self.mode == 'login' else 'auth.action.register')}")
        self.root.addWidget(self._hero(), 1)
        # the registration form is taller than a small window: the panel scrolls instead of squeezing it
        scroll = QScrollArea()
        scroll.setObjectName("authScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self._panel())
        self.root.addWidget(scroll, 1)

    def _hero(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("hero")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(56, 48, 56, 48)
        layout.addStretch(1)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(theme.brand_mark(46, on_color=True))
        name = QLabel(tr("app.name"))
        name.setObjectName("heroTitle")
        brand.addWidget(mark)
        brand.addWidget(name)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(16)
        tagline = label(tr("auth.tagline"), "heroText", wrap=True)
        layout.addWidget(tagline)
        layout.addSpacing(20)
        for icon_name, key in (("folder", "auth.feature.folders"), ("eye", "auth.feature.preview"),
                               ("sync", "auth.feature.sync")):
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(theme.icon_pixmap(icon_name, "#ffffff", 20))
            row.addWidget(icon_label)
            row.addWidget(label(tr(key), wrap=True), 1)
            layout.addLayout(row)
        layout.addStretch(2)
        return hero

    def _field(self, layout: QVBoxLayout, title: str, key: str, password: bool = False,
               placeholder: str = "", hint: str = "", availability: str | None = None) -> QLineEdit:
        layout.addWidget(label(title, "fieldLabel"))
        edit = QLineEdit(self.values.get(key, "") if not password else "")
        edit.setFixedHeight(40)
        if password:
            edit.setEchoMode(QLineEdit.Password)
            self._add_visibility_toggle(edit)
        edit.setPlaceholderText(placeholder)
        layout.addWidget(edit)
        if availability:
            # "this email is already registered" while typing, not only after submitting
            status = label("", "hint", wrap=True)
            status.hide()
            layout.addWidget(status)
            self.availability_labels[availability] = status
            edit.textChanged.connect(lambda _text, f=availability: self._schedule_availability(f))
        self._last_hint = None
        if hint:
            self._last_hint = label(hint, "hint", wrap=True)
            layout.addWidget(self._last_hint)
        layout.addSpacing(6)
        return edit

    @staticmethod
    def _add_visibility_toggle(edit: QLineEdit) -> None:
        """An eye button inside the password field shows / hides what was typed."""
        action = edit.addAction(theme.icon("eye", theme.TEXT_3, 18), QLineEdit.TrailingPosition)
        action.setToolTip(tr("auth.password.show"))

        def toggle():
            show = edit.echoMode() == QLineEdit.Password
            edit.setEchoMode(QLineEdit.Normal if show else QLineEdit.Password)
            action.setIcon(theme.icon("eyeOff" if show else "eye", theme.TEXT_3, 18))
            action.setToolTip(tr("auth.password.hide" if show else "auth.password.show"))

        action.triggered.connect(toggle)

    # --- live checks of the registration form ---------------------------------------------

    def _update_password_rules(self) -> None:
        if self.password_rules is None or self.password_edit is None:
            return
        password = self.password_edit.text()
        rules = [("auth.password.rule.length", len(password) >= self.policy["password_min_length"])]
        if self.policy.get("password_require_uppercase"):
            rules.append(("auth.password.rule.uppercase", has_uppercase(password)))
        if self.policy.get("password_require_special"):
            rules.append(("auth.password.rule.special", has_special(password)))
        lines = [
            f"<span style='color:{theme.SUCCESS if ok else theme.DANGER}'>{'✓' if ok else '✗'} "
            f"{tr(key, min=self.policy['password_min_length'])}</span>"
            for key, ok in rules
        ]
        try:
            self.password_rules.setText("<br>".join(lines))
        except RuntimeError:
            pass  # the form was rebuilt meanwhile

    def _availability_value(self, field: str) -> tuple[str, bool]:
        """(normalized value, has a valid format) of the email or username field."""
        edit = self.email_edit if field == "email" else self.username_edit
        if edit is None:
            return "", False
        value = edit.text().strip().lower()
        pattern = self.policy["email_pattern" if field == "email" else "username_pattern"]
        return value, bool(value) and re.fullmatch(pattern, value) is not None

    def _schedule_availability(self, field: str) -> None:
        self.availability[field] = None
        status = self.availability_labels.get(field)
        if status is not None:
            status.hide()
        self.availability_timers[field].start()

    def _check_availability(self, field: str) -> None:
        value, valid = self._availability_value(field)
        status = self.availability_labels.get(field)
        if status is None or not valid:
            return  # the format itself is reported when the form is submitted
        status.setStyleSheet(f"color: {theme.TEXT_3};")
        status.setText(tr("auth.availability.checking"))
        status.show()
        run_task(ApiClient(self.api_url).availability, **{field: value},
                 on_success=lambda result: self._availability_result(field, value, result.get(field)),
                 on_error=lambda _exc: self._availability_result(field, value, "unknown"))

    def _availability_result(self, field: str, value: str, state: str | None) -> None:
        if self._availability_value(field)[0] != value:
            return  # the user kept typing: a newer check is on its way
        self.availability[field] = state
        status = self.availability_labels.get(field)
        try:
            if state in ("taken", "available"):
                ok = state == "available"
                status.setStyleSheet(f"color: {theme.SUCCESS if ok else theme.DANGER};")
                status.setText(("✓ " if ok else "✗ ") + tr(f"auth.availability.{field}.{state}"))
                status.show()
            else:
                status.hide()
        except RuntimeError:
            pass  # the form was rebuilt meanwhile

    def _panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("authPanel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(40, 18, 24, 24)
        top = QHBoxLayout()
        top.addStretch(1)
        self.lang = Segmented([("uk", "UA"), ("en", "EN")], language())
        self.lang.changed.connect(self.change_language)
        top.addWidget(self.lang)
        outer.addLayout(top)
        outer.addStretch(1)

        form_holder = QHBoxLayout()
        form_holder.addStretch(1)
        form = QWidget()
        form.setFixedWidth(380)
        layout = QVBoxLayout(form)
        layout.setSpacing(4)
        is_login = self.mode == "login"
        layout.addWidget(label(tr("auth.login.title" if is_login else "auth.register.title"), "authTitle"))
        layout.addWidget(label(tr("auth.login.subtitle" if is_login else "auth.register.subtitle"), "muted"))
        layout.addSpacing(10)

        self.alert = Alert("error")
        self.alert.hide()
        layout.addWidget(self.alert)

        self.availability_labels = {}
        self.availability = {"email": None, "username": None}
        self.password_rules = None
        if is_login:
            self.identifier_edit = self._field(layout, tr("auth.field.identifier"), "identifier")
            self.email_edit = self.username_edit = self.display_name_edit = None
            self.password_edit = self._field(layout, tr("auth.field.password"), "password", password=True)
        else:
            self.identifier_edit = None
            self.password_confirm_edit = None
            self.email_edit = self._field(layout, tr("auth.field.email"), "email", availability="email")
            self.username_edit = self._field(layout, tr("auth.field.username"), "username",
                                             hint=tr("auth.field.usernameHint"), availability="username")
            self.display_name_edit = self._field(layout, tr("auth.field.displayName"), "display_name",
                                                 placeholder=tr("auth.field.optional"))
            self.password_edit = self._field(layout, tr("auth.field.password"), "password", password=True,
                                             hint=" ")
            # live checklist instead of a static hint: length, capital letter, special sign
            self.password_rules = self.password_hint = self._last_hint
            self.password_rules.setTextFormat(Qt.RichText)
            self.password_edit.textChanged.connect(lambda _text: self._update_password_rules())
            self._update_password_rules()
            self.password_confirm_edit = self._field(layout, tr("auth.field.passwordConfirm"), "password_confirm",
                                                     password=True)
            for field in ("email", "username"):
                if self._availability_value(field)[1]:  # a value kept from the login form
                    self._schedule_availability(field)

        self.submit = button(tr("auth.action.login" if is_login else "auth.action.register"), "primary")
        self.submit.setDefault(True)
        self.submit.clicked.connect(self.login if is_login else self.register)
        layout.addSpacing(6)
        layout.addWidget(self.submit)

        switch = QHBoxLayout()
        switch.addStretch(1)
        switch.addWidget(label(tr("auth.switch.noAccount" if is_login else "auth.switch.hasAccount"), "muted"))
        link = QPushButton(tr("auth.action.register" if is_login else "auth.action.login"))
        link.setProperty("variant", "ghost")
        link.setCursor(Qt.PointingHandCursor)
        link.setStyleSheet(f"color: {theme.PRIMARY}; padding: 4px 6px;")
        link.clicked.connect(lambda: self.switch_mode("register" if is_login else "login"))
        switch.addWidget(link)
        switch.addStretch(1)
        layout.addLayout(switch)

        form_holder.addWidget(form)
        form_holder.addStretch(1)
        outer.addLayout(form_holder)
        outer.addStretch(2)

        first = (self.identifier_edit if is_login and not self.identifier_edit.text() else
                 self.password_edit if is_login else self.email_edit)
        first.setFocus()
        return panel

    # --- interaction ---------------------------------------------------------------------

    def change_language(self, lang: str) -> None:
        self._remember_inputs()
        set_language(lang)
        self.settings.setValue("language", lang)
        self.build()

    def switch_mode(self, mode: str) -> None:
        self._remember_inputs()
        if mode == "register":
            typed = self.values.get("identifier", "").strip()
            if typed and not self.values.get("email") and "@" in typed:
                self.values["email"] = typed
            elif typed and not self.values.get("username") and "@" not in typed:
                self.values["username"] = typed.lower()
        self.mode = mode
        self.build()

    def _policy_loaded(self, policy: dict) -> None:
        self.policy = policy
        self._update_password_rules()

    def _show_problems(self, problems: list[str]) -> None:
        """Every problem of the form at once (same texts as the web client)."""
        self._busy(False)
        self.alert.clear_actions()
        texts = [tr(f"error.{p}", min=self.policy["password_min_length"]) for p in problems]
        if len(texts) == 1:
            self.alert.show_message("error", texts[0])
        else:
            self.alert.show_message("error", "", "\n".join(f"• {text}" for text in texts))
            self.alert.set_tone("error")

    def _client(self) -> ApiClient:
        return ApiClient(self.api_url)

    def _busy(self, busy: bool) -> None:
        self.submit.setEnabled(not busy)
        self.submit.setText(tr("auth.action.wait") if busy else
                            tr("auth.action.login" if self.mode == "login" else "auth.action.register"))

    def _show_error(self, exc: BaseException | None, text: str | None = None) -> None:
        self._busy(False)
        self.alert.clear_actions()
        code = getattr(exc, "code", None)
        problems = (getattr(exc, "extra", None) or {}).get("problems")
        if problems:  # the server checked the same rules and lists everything it found
            self._show_problems(problems)
            return
        self.alert.show_message("error", text or describe_error(exc))
        if self.mode == "login" and code == "user_not_found":
            action = button(tr("auth.action.register"), "secondary")
            action.clicked.connect(lambda: self.switch_mode("register"))
            self.alert.actions.addWidget(action)
            self.alert.actions.addStretch(1)
        if self.mode == "register" and code == "user_exists":
            action = button(tr("auth.action.login"), "secondary")
            action.clicked.connect(lambda: self.switch_mode("login"))
            self.alert.actions.addWidget(action)
            self.alert.actions.addStretch(1)

    def login(self) -> None:
        identifier = self.identifier_edit.text().strip()
        password = self.password_edit.text()
        problems = login_problems(identifier, password)
        if problems:
            self._show_problems(problems)
            return
        client = self._client()
        self._busy(True)
        self.alert.hide()

        def done(_):
            self.settings.setValue("identifier", identifier)
            self.api = client
            self.accept()

        run_task(client.login, identifier, password, on_success=done, on_error=self._show_error)

    def register(self) -> None:
        email = self.email_edit.text().strip()
        username = self.username_edit.text().strip().lower()
        password = self.password_edit.text()
        password_confirm = self.password_confirm_edit.text()
        problems = registration_problems(email, username, password, password_confirm, self.policy)
        if self.availability.get("email") == "taken":
            problems.append("user_exists")
        if self.availability.get("username") == "taken":
            problems.append("username_taken")
        if problems:
            self._show_problems(problems)
            return
        client = self._client()
        self._busy(True)

        def done(result: dict):
            self._busy(False)
            if client.access_token:
                self.settings.setValue("identifier", username)
                self.api = client
                self.accept()
                return
            self._remember_inputs()
            self.values["identifier"] = username
            self.mode = "login"
            self.build()
            self.alert.show_message("info", tr("auth.registeredConfirm"))

        run_task(client.register, email, password, self.display_name_edit.text().strip(), username, password_confirm,
                 on_success=done, on_error=self._show_error)

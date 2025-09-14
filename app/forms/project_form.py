# app/forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, PasswordField
from wtforms.validators import DataRequired, Length

class ProjectCreateForm(FlaskForm):
    name = StringField("Název projektu", validators=[DataRequired(), Length(min=2, max=120)])
    type = SelectField(
        "Typ projektu",
        choices=[("web", "Web"), ("e2e", "E2E testy")],
        validators=[DataRequired()],
    )
    description = TextAreaField("Popis", validators=[Length(max=1000)])
    visibility = SelectField(
        "Viditelnost",
        choices=[("private", "Soukromý"), ("link-only", "Na odkaz"), ("public", "Veřejný")],
        default="private",
        validators=[DataRequired()],
    )
    passphrase = PasswordField("Heslo k projektu (volitelné)")
    # POZOR: logo pole bereme přes request.files['logo'] v route (multipart form)

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, BooleanField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange

class SuiteForm(FlaskForm):
    name        = StringField("Název", validators=[DataRequired(), Length(max=180)])
    description = TextAreaField("Popis")
    parent_id   = SelectField("Nadřazená sekce", coerce=int, choices=[])  # 0 = žádná (tedy SEKCE)
    order_index = IntegerField("Pořadí", default=0, validators=[NumberRange(min=0)])
    is_active   = BooleanField("Aktivní", default=True)
    submit      = SubmitField("Uložit")
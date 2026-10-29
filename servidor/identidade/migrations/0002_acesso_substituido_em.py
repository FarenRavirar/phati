from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('comum', '0001_privilegios_app'),
        ('identidade', '0001_inicial'),
    ]

    operations = [
        migrations.AddField(
            model_name='acessoaplicativo',
            name='substituido_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

# Generated manually for level_percentages field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adminPanel', '0017_remove_bankdetailsrequest_branch_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='commissioningprofile',
            name='level_percentages',
            field=models.CharField(blank=True, null=True, help_text="Comma-separated percentages for each level (e.g., '50,20,20,10')", max_length=255),
        ),
    ]

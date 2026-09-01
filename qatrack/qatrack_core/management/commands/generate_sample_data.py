
from django.core.management.base import BaseCommand, CommandError

from qatrack.qatrack_core.sample_data import SmallCenterGenerator


class Command(BaseCommand):
    help = "Generates comprehensive, realistic sample test data for QATrack+ (QA, Service Log, Faults, Parts, Reports)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--size",
            type=str,
            default="small",
            choices=["small", "medium", "large"],
            help="Size and profile of the radiation oncology center to generate (default: small).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Number of days of rolling QA and maintenance history to generate (default: 90).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing QA, unit, service log, fault, parts, and report data before generating.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not prompt for confirmation when clearing data.",
        )

    def handle(self, *args, **options):
        size = options["size"]
        days = options["days"]
        clear = options["clear"]
        no_input = options["no_input"]

        generators = {
            "small": SmallCenterGenerator,
        }

        if size not in generators:
            raise CommandError(f"Center size '{size}' is not implemented yet. Available sizes: {', '.join(generators.keys())}")

        generator_class = generators[size]
        generator = generator_class(days=days, stdout=self.stdout, stderr=self.stderr)

        if clear:
            if not no_input:
                confirm = input("This will DELETE existing units, QA records, service events, faults, parts, and reports. Continue? [y/N]: ")
                if confirm.lower() != "y":
                    self.stdout.write(self.style.WARNING("Aborted by user."))
                    return

            generator.clear_database()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Generating '{size}' center with {days} days of history..."))
        generator.generate()
        self.stdout.write(self.style.SUCCESS(f"Successfully generated sample data for '{size}' center!"))

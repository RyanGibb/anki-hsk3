"""What the syllabus fixes, and every step of the build reads the same way."""
import re

# The levels in the order they are taught. 7-9 is one level to the syllabus.
LEVELS = ["1", "2", "3", "4", "5", "6", "7-9"]
LEVEL_ORDER = {lv: i for i, lv in enumerate(LEVELS)}

# A word's parts of speech as the word lists write them: 对 is 形、介、（动、量）, listed
# with 、 and some of them bracketed, and the other list separates with a slash.
POS_SPLIT = re.compile(r"[、,／/（）()]+")

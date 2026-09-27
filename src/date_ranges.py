"""Deterministic calendar parsing. No LLM, implicit year substitution, or I/O."""
import calendar
from datetime import date, timedelta
import re

MONTHS = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}
MONTH = '(?:' + '|'.join(MONTHS) + ')'


def format_range(start, end):
    return f'{start:%b} {start.day}, {start.year}–{end:%b} {end.day}, {end.year}'


def parse_date_range(question, today, data_start, data_end):
    """Inclusive dates; bounds describe actual dataset coverage, not UI dates.

    Return requested/effective date objects, label, status, and remaining_question.
    Partial coverage returns an overlap but callers must not calculate it unless
    explicitly requested. Invalid/conflicting dates receive status 'invalid'.
    A trailing year on a named range applies to both endpoints; absent years
    default to today.year. Reversed ranges are invalid rather than rolled forward.
    """
    q = question.lower().strip().rstrip(".?! ")
    start = end = None
    span = None
    label = ''
    patterns = [
        ('iso', r'\b(?:from\s+)?(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b'),
        ('range', rf'\b(?:from\s+)?({MONTH})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?\s+to\s+({MONTH})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?\b'),
        ('relative', r'\b(last year|this year|year to date|ytd|last 30 days|last month|this month|this quarter|last quarter|previous quarter|available period)\b'),
        ('quarter', r'\bq([1-4])(?:\s+(\d{4}))?\b'),
        ('month', rf'\b({MONTH})(?:\s+(\d{{4}}))?\b'),
        ('year', r'(?<![\d-])\b((?:19|20)\d{2})\b(?!-\d)'),
    ]
    try:
        for kind, pattern in patterns:
            m = re.search(pattern, q)
            if not m:
                continue
            span = m.span(); label = m.group(0)
            if kind == 'iso':
                start, end = date.fromisoformat(m[1]), date.fromisoformat(m[2])
            elif kind == 'range':
                year1, year2 = int(m[3] or m[6] or today.year), int(m[6] or m[3] or today.year)
                start, end = date(year1, MONTHS[m[1]], int(m[2])), date(year2, MONTHS[m[4]], int(m[5]))
            elif kind == 'relative':
                if label in ('this quarter', 'last quarter', 'previous quarter'):
                    month = ((today.month - 1)//3)*3 + 1
                    anchor = today.replace(month=month, day=1)
                    if label != 'this quarter':
                        anchor = anchor - timedelta(days=1)
                        anchor = anchor.replace(month=((anchor.month-1)//3)*3+1, day=1)
                    start = anchor
                    end_month = anchor.month + 2
                    end = date(anchor.year, end_month, calendar.monthrange(anchor.year,end_month)[1])
                elif label == 'available period':
                    start, end = data_start, data_end
                elif label == 'last year':
                    start, end = date(today.year-1, 1, 1), date(today.year-1, 12, 31)
                elif label in ('this year', 'year to date', 'ytd'):
                    start, end = date(today.year, 1, 1), today
                elif label == 'last 30 days':
                    start, end = today - timedelta(days=29), today
                elif label == 'this month':
                    start, end = today.replace(day=1), today
                else:
                    end = today.replace(day=1) - timedelta(days=1)
                    start = end.replace(day=1)
            elif kind == 'year':
                start, end = date(int(m[1]), 1, 1), date(int(m[1]), 12, 31)
            elif kind == 'quarter':
                month, year = (int(m[1])-1)*3+1, int(m[2] or today.year)
                start, end = date(year, month, 1), date(year, month+2, calendar.monthrange(year, month+2)[1])
            else:
                month, year = MONTHS[m[1]], int(m[2] or today.year)
                start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
            break
        remaining = q if span is None else q[:span[0]] + q[span[1]:]
        # Do not answer a guessed subset of multiple periods or malformed dates.
        if span and (any(re.search(pattern, remaining) for _, pattern in patterns) or re.search(r'\b\d{4}\b|\bq\d\b|\b\d{1,2}\b', remaining)):
            # Provider numeric aliases are not date phrases.
            cleaned = re.sub(r'\bprovider\s*\d+\b|\b\d{1,3}%', '', remaining)
            if any(re.search(pattern, cleaned) for _, pattern in patterns) or re.search(r'\b\d{4}\b|\bq\d\b|\b\d{1,2}\b', cleaned):
                raise ValueError('Ambiguous date expression')
        if span is None:
            if re.search(r'\bq\d\b|\b\d{4}-\d{2}-\d{2}\b', q):
                raise ValueError('Unsupported date')
            status = 'no_date_requested'
            effective_start = effective_end = None
        elif start is None or end is None:
            status = 'unavailable'; effective_start = effective_end = None
        elif start > end:
            raise ValueError('Reversed range')
        elif data_start is None or data_end is None or end < data_start or start > data_end:
            status = 'unavailable'; effective_start = effective_end = None
        else:
            effective_start, effective_end = max(start, data_start), min(end, data_end)
            status = 'ok' if (start, end) == (effective_start, effective_end) else 'partially_available'
        remaining = re.sub(r'\b(?:during|in|for|from|over)\s*(?:the\s*)?$', '', remaining.strip()).strip()
        return dict(requested_start=start, requested_end=end, effective_start=effective_start,
                    effective_end=effective_end, label=label, status=status, remaining_question=remaining)
    except (ValueError, OverflowError):
        return dict(requested_start=None, requested_end=None, effective_start=None,
                    effective_end=None, label=label, status='invalid', remaining_question=q)


def parse_comparison_ranges(question, today, data_start, data_end):
    """Resolve two supported periods separated by vs/versus, without an LLM.

    For named months, one explicit year applies to both endpoints unless each
    month supplies its own year. Absent years use today.year, never dataset year.
    Return None for a provider-vs-provider comparison without date expressions.
    """
    parts = re.split(r'\b(?:vs\.?|versus)\s+', question.lower(), maxsplit=1)
    if len(parts) != 2:
        return None
    left, right = parts
    month_only = rf'\b{MONTH}\b(?!\s+\d)'
    left_years, right_years = re.findall(r'\b\d{4}\b', left), re.findall(r'\b\d{4}\b', right)
    if not left_years and len(right_years) == 1 and re.search(month_only, left):
        left = re.sub(month_only, lambda m: m[0] + ' ' + right_years[0], left)
    if not right_years and len(left_years) == 1 and re.search(month_only, right):
        right = re.sub(month_only, lambda m: m[0] + ' ' + left_years[0], right)
    periods = [parse_date_range(part, today, data_start, data_end) for part in (left, right)]
    if all(p['status'] == 'no_date_requested' for p in periods):
        return None
    return periods


def previous_window(start, end):
    """Prior calendar month/year for those windows, otherwise equal-length prior.

    A month-to-date window compares the same day numbers in the prior month,
    capped at its last day. Full calendar years compare the prior calendar year.
    """
    if start.month == 1 and start.day == 1 and end == date(start.year, 12, 31):
        return date(start.year-1, 1, 1), date(start.year-1, 12, 31)
    if start.day == 1 and start.month in (1,4,7,10) and end == date(start.year,start.month+2,calendar.monthrange(start.year,start.month+2)[1]):
        prior_end = start - timedelta(days=1)
        return prior_end.replace(month=((prior_end.month-1)//3)*3+1,day=1), prior_end
    if start.day == 1 and start.year == end.year and start.month == end.month:
        prior_end = start - timedelta(days=1)
        full_month = end.day == calendar.monthrange(end.year, end.month)[1]
        return prior_end.replace(day=1), prior_end if full_month else prior_end.replace(day=min(end.day, prior_end.day))
    return start - (end-start+timedelta(days=1)), start-timedelta(days=1)


def latest_month_windows(start, end):
    """Two complete calendar months contained in observed dashboard bounds."""
    current_end = end
    if end.day != calendar.monthrange(end.year, end.month)[1]:
        current_end = end.replace(day=1) - timedelta(days=1)
    current = (current_end.replace(day=1), current_end)
    prior = previous_window(*current)
    return prior, current

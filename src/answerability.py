"""One fallback policy shared by every text and voice query route."""
import re

QUESTION_CATALOG = {
    'Overview': ['Summarize performance', 'Show completed visits and utilization by clinic', 'Show utilization by specialty'],
    'Revenue': ['Show revenue by clinic', 'Show revenue per visit by provider', 'Show revenue opportunity by provider'],
    'Appointments': ['Show no-show rate by provider', 'Show unused capacity by provider', 'Show completed visits by clinic'],
    'Definitions': ['What does utilization mean?', 'How is revenue opportunity calculated?', 'Explain productivity'],
}


def suggested_candidates(question, empty=False):
    q=question.lower()
    if empty: return QUESTION_CATALOG['Definitions']
    topic='Revenue' if re.search(r'revenue|collections|profit|financial',q) else 'Appointments' if re.search(r'patient|visit|capacity|no.show|appointment',q) else 'Overview'
    return list(dict.fromkeys(QUESTION_CATALOG[topic]+QUESTION_CATALOG['Overview']+QUESTION_CATALOG['Definitions']))


def finish_answer(response, question, df, probe):
    """Keep the reason, replace inconsistent route-specific alternatives.

    Probe a bounded catalog with the same data/clock to avoid suggesting an
    unavailable date, missing entity, or unsupported metric. No recursive public
    respond() calls, no model calls and no free-form generated suggestions.
    """
    if response['status']=='answered': return response
    choices=[]
    # Never aggregate as a side effect of an unavailable/partial/invalid date request.
    # Definition questions are useful and answerable without calculating a period.
    definitions = (['How is revenue opportunity calculated?', 'Explain revenue per visit', 'Explain revenue']
                   if re.search(r'revenue|collections|profit', question.lower()) else
                   ['Explain visits', 'Explain no-show rate', 'Explain capacity']
                   if re.search(r'patient|visit|appointment|no.show', question.lower()) else QUESTION_CATALOG['Definitions'])
    candidates = (definitions if response['status'] in ('unavailable', 'partially_available', 'invalid')
                  else suggested_candidates(question,df.empty))
    for candidate in candidates:
        if probe(candidate)['status']=='answered': choices.append(candidate)
        if len(choices)==3: break
    # Catalog definitions remain useful when no rows exist.
    response['suggested_questions']=choices
    text=re.split(r'\n\n(?:You can ask instead:|After selecting a date range and team with available data, try:)',response['text'],maxsplit=1)[0]
    intro='After selecting a date range and team with available data, try:' if df.empty else 'You can ask instead:'
    response['text']=text+'\n\n'+intro+'\n'+'\n'.join('- '+q for q in choices)
    response['follow_ups']=[]
    return response

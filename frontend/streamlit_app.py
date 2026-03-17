import os
from datetime import time
import pandas as pd
import requests
import streamlit as st

API_BASE = os.getenv('API_BASE_URL', 'http://localhost:8000')
st.set_page_config(page_title='AI Life-Load Assistant', page_icon='🌿', layout='wide')

def safe_get(path, params=None):
    try:
        r = requests.get(API_BASE.rstrip('/') + path, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {'error': str(exc)}

def safe_post(path, payload):
    r = requests.post(API_BASE.rstrip('/') + path, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def safe_delete(path):
    r = requests.delete(API_BASE.rstrip('/') + path, timeout=30)
    r.raise_for_status()
    return r.json()

def backend_chat_response(question):
    history = st.session_state.get('messages', [])
    payload = {
        'message': question,
        'members': st.session_state.get('selected_members', 2),
        'meal_type': st.session_state.get('selected_meal_type', 'Any'),
        'history': [
            {'role': m['role'], 'content': m['content']}
            for m in history
            if m['role'] in ['user', 'assistant']
        ],
    }
    result = safe_post('/chat/assistant', payload)
    answer = result.get('answer', '').strip()
    if not answer:
        answer = "Assistant returned an empty reply. Please try once more."
    return answer


def load_label(workload):
    mapping = {'Free day': 'Free', 'Light workload': 'Light', 'Moderate workload': 'Moderate', 'Heavy workload': 'Heavy'}
    return mapping.get(workload, workload)

def load_explanation(workload):
    mapping = {
        'Free day': 'Very few time pressures today.',
        'Light workload': 'Manageable day with enough breathing space.',
        'Moderate workload': 'Busy but manageable. Quick decisions help.',
        'Heavy workload': 'Packed day. Keep meals and tasks simple.',
    }
    return mapping.get(workload, '')

def evening_explanation(workload):
    mapping = {
        'Free day': 'Evening looks free, so fuller balanced dinners can be suggested.',
        'Light workload': 'Evening is light, so you have some flexibility for dinner.',
        'Moderate workload': 'Evening is moderately packed, so 20–40 min dinners are preferred.',
        'Heavy workload': 'Evening is packed, so quick low-effort dinners are preferred.',
    }
    return mapping.get(workload, '')

st.markdown("""
<style>
.main-banner {padding: 1rem 1.2rem 0.6rem 1.2rem; border-radius: 18px; background: linear-gradient(90deg, #eef6ff, #f7fbff); border: 1px solid #dbeafe; margin-bottom: 1rem;}
.small-muted {color:#6b7280; font-size:0.95rem;}
.tiny-label {font-size:0.76rem; color:#6b7280; margin-bottom:0.1rem;}
.tiny-value {font-size:1.25rem; font-weight:600; line-height:1.0;}
.tiny-help {font-size:0.72rem; color:#6b7280;}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header('Assistant Controls')
    members = st.selectbox('Family members', [1,2,3,4,5], index=1)
    meal_type = st.selectbox('Meal type', ['Any','Breakfast','Lunch','Dinner'])
    st.session_state['selected_members'] = members
    st.session_state['selected_meal_type'] = meal_type
    st.markdown('---')
    st.subheader('Add Household Chore')
    with st.form('chore_form', clear_on_submit=True):
        chore_title = st.text_input('Chore name')
        chore_time = st.time_input('Preferred time', value=time(18,0))
        chore_duration = st.number_input('Duration (min)', min_value=5, max_value=180, value=15, step=5)
        chore_priority = st.selectbox('Priority', ['high','medium','low'])
        if st.form_submit_button('Add new chore') and chore_title.strip():
            safe_post('/chores', {'title': chore_title.strip(), 'preferred_time': chore_time.strftime('%H:%M'), 'duration_min': int(chore_duration), 'due_today': True, 'priority': chore_priority})
            st.rerun()
    st.subheader('Add Mandatory Routine')
    with st.form('routine_form', clear_on_submit=True):
        routine_title = st.text_input('Routine / mandatory task')
        routine_time = st.time_input('Start time', value=time(7,0), key='routine_time')
        routine_duration = st.number_input('Duration (min)', min_value=5, max_value=240, value=30, step=5)
        routine_category = st.selectbox('Category', ['personal','kids','meal','family','travel','work'])
        if st.form_submit_button('Add new routine') and routine_title.strip():
            safe_post('/mandatory-tasks', {'title': routine_title.strip(), 'start_time': routine_time.strftime('%H:%M'), 'duration_min': int(routine_duration), 'category': routine_category})
            st.rerun()

today = safe_get('/dashboard/today')
meal_data = safe_get('/meal/plan', params={'members': members, 'meal_type': meal_type})
weekly = safe_get('/dashboard/weekly-summary')
inventory = safe_get('/inventory')
yesterday = safe_get('/dashboard/yesterday')
tomorrow = safe_get('/dashboard/tomorrow')
wellbeing_day = safe_get('/wellbeing/activity', params={'context':'day'})
wellbeing_bed = safe_get('/wellbeing/activity', params={'context':'bedtime'})
habit_memory = safe_get('/memory/habits')

if today.get('error'):
    st.error(today['error'])
    st.stop()

st.markdown(f"""
<div class="main-banner">
    <h1 style="margin-bottom:0.25rem;">🌿 AI Life-Load Assistant</h1>
    <div class="small-muted">Calendar-aware planning, persistent home routines, inventory-led meal suggestions, and proactive preparation support.</div>
</div>
""", unsafe_allow_html=True)

view = st.radio('View', ['Today', 'Yesterday', 'Tomorrow'], horizontal=True)

if view == 'Yesterday':
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Meetings', yesterday.get('calendar_events_count', 0))
    c2.metric('Mandatory', yesterday.get('mandatory_meetings', 0))
    c3.metric('Optional', yesterday.get('optional_meetings', 0))
    c4.metric('Stress', yesterday.get('stress_score', 0))
    st.subheader('Yesterday Quick Summary')
    st.info(yesterday.get('quick_summary', 'No data available.'))
    st.caption('Yesterday view is intentionally compact.')
    st.stop()

if view == 'Tomorrow':
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Meetings', tomorrow.get('calendar_events_count', 0))
    c2.metric('Mandatory', tomorrow.get('mandatory_meetings', 0))
    c3.metric('Optional', tomorrow.get('optional_meetings', 0))
    c4.metric('Stress', tomorrow.get('stress_score', 0))
    left, right = st.columns([1.2, 0.8])
    with left:
        st.subheader('Tomorrow Dashboard')
        events = tomorrow.get('events', [])
        if events:
            st.dataframe(pd.DataFrame(events)[['summary','start','end','priority']], use_container_width=True, height=260)
        else:
            st.caption('No meetings on calendar tomorrow.')
    with right:
        st.subheader('Night-Before Preparation Ideas')
        for idea in tomorrow.get('prep_ideas', []):
            st.success(idea)
        st.subheader("Tomorrow's Breakfast Options")
        for item in tomorrow.get('tomorrow_breakfast', [])[:3]:
            st.write(f"• {item['recipe_name']} ({item['total_time_min']} min)")
    st.stop()

row1 = st.columns([1,1,1,1,1.2])
row1[0].metric('Meetings Today', today.get('calendar_events_count', 0))
row1[1].metric('Mandatory Meetings', today.get('mandatory_meetings', 0))
row1[2].metric('Optional Meetings', today.get('optional_meetings', 0))
row1[3].metric('Stress Score', today.get('stress_score', 0))
with row1[4]:
    st.markdown('**Weekly Summary**')
    st.caption(f"{weekly.get('weekly_time_saved_hours', 0)} hrs saved this week")
    st.caption(weekly.get('insight', ''))

left, right = st.columns([1.05, 0.95])

with left:
    st.subheader("Today's Summary")
    st.info(today.get('ai_summary', {}).get('headline', ''))
    r = st.columns(4)
    workload = today.get('workload_level', '-')
    with r[0]:
        st.markdown(f"<div class='tiny-label'>Day Load</div><div class='tiny-value'>{load_label(workload)}</div><div class='tiny-help'>{load_explanation(workload)}</div>", unsafe_allow_html=True)
    with r[1]:
        st.markdown(f"<div class='tiny-label'>Chores</div><div class='tiny-value'>{today.get('household_chores_count', 0)}</div><div class='tiny-help'>Today’s added household work items</div>", unsafe_allow_html=True)
    with r[2]:
        st.markdown(f"<div class='tiny-label'>Fixed Routines</div><div class='tiny-value'>{today.get('mandatory_tasks_count', 0)}</div><div class='tiny-help'>Persistent daily non-calendar commitments</div>", unsafe_allow_html=True)
    with r[3]:
        evening_load = today.get('evening_workload_level', '-')
        st.markdown(f"<div class='tiny-label'>Evening Load</div><div class='tiny-value'>{load_label(evening_load)}</div><div class='tiny-help'>{evening_explanation(evening_load)}</div>", unsafe_allow_html=True)

    with st.expander('Calendar events', expanded=True):
        events = today.get('calendar_events', [])
        if events:
            st.dataframe(pd.DataFrame(events)[['summary','start','end','priority']], use_container_width=True, height=220)
        else:
            st.caption('No meetings on calendar today.')

    with st.expander('View household chores', expanded=False):
        chores = today.get('household_chores', [])
        if chores:
            for idx, item in enumerate(chores):
                a, b = st.columns([7,1])
                a.markdown(f"<div class='tiny-help'>• {item['title']} — {item.get('preferred_time','')} — {item.get('duration_min',0)} min — {item.get('priority','')}</div>", unsafe_allow_html=True)
                if b.button('🗑️', key=f"delete_chore_{idx}_{item['title']}"):
                    safe_delete(f'/chores/{idx}')
                    st.rerun()
        else:
            st.caption('No items added yet.')

    with st.expander('View fixed routines', expanded=False):
        tasks = today.get('mandatory_tasks', [])
        if tasks:
            for idx, item in enumerate(tasks):
                a, b = st.columns([7,1])
                a.markdown(f"<div class='tiny-help'>• {item['title']} — {item.get('start_time','')} — {item.get('duration_min',0)} min — {item.get('category','')}</div>", unsafe_allow_html=True)
                if b.button('🗑️', key=f"delete_routine_{idx}_{item['title']}"):
                    safe_delete(f'/mandatory-tasks/{idx}')
                    st.rerun()
        else:
            st.caption('No items added yet.')

with right:
    st.subheader('Meal Suggestions')
    plan = meal_data.get('meal_plan', {})
    dinner_plan = today.get('dinner_plan', {})
    if meal_type == 'Dinner':
        st.caption('Dinner suggestions below are based on your evening schedule load.')
    else:
        st.caption(plan.get('recommendation_reason', ''))
    st.caption(f"Expand a meal to see ingredient quantities for {members} family member(s).")

    active_plan = dinner_plan if meal_type == 'Dinner' else plan
    recs = active_plan.get('recommended_meals', [])
    if recs:
        for idx, item in enumerate(recs):
            label = item.get('one_liner') or f"{item['recipe_name']} • {item.get('meal_type','')} • {item.get('total_time_min','-')} min"
            with st.expander(label, expanded=False):
                st.write(f"Reason: {item.get('reason_line','Suggested for your current day load.')}")
                ing = item.get('ingredient_list', [])
                if ing:
                    df = pd.DataFrame(ing)[['ingredient','required_qty','unit','available_qty','inventory_unit','mandatory']]
                    df.columns = ['Ingredient', 'Required Qty', 'Unit', 'Available Qty', 'Inventory Unit', 'Mandatory']
                    st.dataframe(df, use_container_width=True, hide_index=True)

                made_choice = st.radio(f"Did you make {item['recipe_name']}?", ['Yes', 'No'], horizontal=True, key=f"made_choice_{idx}_{item['recipe_name']}")
                custom_text = ''
                actual_time = None
                selected_slot = meal_type if meal_type != 'Any' else item.get('meal_type', 'Any')
                if made_choice == 'Yes':
                    actual_time = st.number_input(f"How many minutes did {item['recipe_name']} actually take?", min_value=1, max_value=180, value=int(item.get('total_time_min', 20)), step=1, key=f"actual_time_{idx}_{item['recipe_name']}")
                else:
                    custom_text = st.text_input(f"What did you cook instead for {selected_slot}?", key=f"custom_food_{idx}_{item['recipe_name']}")
                if st.button(f"Save meal decision for {item['recipe_name']}", key=f"save_meal_{idx}_{item['recipe_name']}"):
                    payload = {'recipe_name': item['recipe_name'], 'members': members, 'meal_slot': selected_slot, 'made_recipe': made_choice == 'Yes', 'custom_cooked': custom_text, 'actual_time_min': actual_time}
                    result = safe_post('/meal/confirm', payload)
                    st.success(result.get('message', 'Saved.'))
                    st.rerun()
    else:
        st.warning('No recommended meals right now.')

    unavailable = active_plan.get('unavailable_meals', [])
    if unavailable:
        st.markdown('**Currently unavailable suggestions**')
        for item in unavailable[:3]:
            st.error(f"{item['recipe_name']}: " + '; '.join(item.get('missing_mandatory', [])))

    if active_plan.get('suggested_purchase_items'):
        st.markdown('**Suggested grocery purchase**')
        st.write(', '.join(active_plan['suggested_purchase_items']))

    with st.expander('View inventory', expanded=False):
        items = inventory.get('items', [])
        if items:
            st.dataframe(pd.DataFrame(items), use_container_width=True, height=220)

    with st.expander('View wellbeing activity', expanded=False):
        st.markdown(f"**{wellbeing_day.get('title','Wellbeing Reset')}**")
        st.write(f"Duration: {wellbeing_day.get('duration','')}")
        st.write(f"Pattern: {wellbeing_day.get('pattern','')}")
        st.caption(wellbeing_day.get('reason',''))
        for step in wellbeing_day.get('steps', []):
            st.write('• ' + step)
        st.markdown('---')
        st.markdown(f"**Before Bed Recommendation: {wellbeing_bed.get('title','Night Deep Breathing')}**")
        st.write(f"Duration: {wellbeing_bed.get('duration','')}")
        st.write(f"Pattern: {wellbeing_bed.get('pattern','')}")
        st.caption(wellbeing_bed.get('reason',''))
        for step in wellbeing_bed.get('steps', []):
            st.write('• ' + step)

    with st.expander('View learned habits', expanded=False):
        fastest = habit_memory.get('fastest_recipes', [])
        if fastest:
            st.markdown('**Your learned recipe timings**')
            for item in fastest:
                st.write(f"• {item['recipe_name']} — avg {item['avg_time_min']} min over {item['made_count']} time(s)")
        notes = habit_memory.get('summary_notes', [])
        if notes:
            st.markdown('**Recent learning notes**')
            for note in notes[-5:]:
                st.write(f"• {note}")

st.divider()
st.subheader('Chat with your assistant')
if 'messages' not in st.session_state:
    st.session_state.messages = [{'role':'assistant','content':'Hi Mahima 👋 I reviewed your calendar, routines, grocery signals, and evening load. Ask me about meals, dinner ideas, planning, or what to prepare for tomorrow.'}]
for msg in st.session_state.messages:
    with st.chat_message(msg['role']):
        st.markdown(msg['content'])
prompt = st.chat_input('Ask something like: suggest breakfast for 3 people')
if prompt:
    st.session_state.messages.append({'role':'user','content':prompt})
    with st.chat_message('user'):
        st.markdown(prompt)
    answer = backend_chat_response(prompt)
    st.session_state.messages.append({'role':'assistant','content':answer})
    with st.chat_message('assistant'):
        st.markdown(answer)

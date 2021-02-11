from typing import Dict, List
import logging
from copy import deepcopy
from common.universal_templates import if_lets_chat_about_topic
from common.utils import service_intents, get_topics, get_intents

logger = logging.getLogger(__name__)

LAST_N_TURNS = 5  # number of turns to consider in annotator/skill.


def get_last_n_turns(dialog: Dict, bot_last_turns=None, human_last_turns=None, total_last_turns=None):
    bot_last_turns = bot_last_turns or LAST_N_TURNS
    human_last_turns = human_last_turns or bot_last_turns + 1
    total_last_turns = total_last_turns or bot_last_turns * 2 + 1

    new_dialog = {}
    for key, value in dialog.items():
        if key not in ["utterances", "human_utterances", "bot_utterances"]:
            new_dialog[key] = deepcopy(value)
    new_dialog["utterances"] = deepcopy(dialog["utterances"][-total_last_turns:])

    new_dialog["human_utterances"] = []
    new_dialog["bot_utterances"] = []

    for utt in new_dialog["utterances"]:
        if utt['user']['user_type'] == 'human':
            new_dialog["human_utterances"].append(deepcopy(utt))
        elif utt['user']['user_type'] == 'bot':
            new_dialog["bot_utterances"].append(deepcopy(utt))

    return new_dialog


def is_human_uttr_repeat_request_or_misheard(utt):
    is_repeat_request = utt.get('annotations', {}).get("intent_catcher", {}).get("repeat", {}).get("detected", 0) == 1
    is_low_asr_conf = utt.get('annotations', {}).get('asr', {}).get('asr_confidence', "") == 'very_low'
    if is_low_asr_conf or is_repeat_request:
        return True
    else:
        return False


def is_bot_uttr_repeated_or_misheard(utt):
    is_asr = utt.get("active_skill", "") == "misheard_asr" and utt.get("confidence", 0.) == 1.
    is_repeated = "#+#repeat" in utt.get("text", "")
    if is_asr or is_repeated:
        return True
    else:
        return False


def remove_clarification_turns_from_dialog(dialog):
    new_dialog = deepcopy(dialog)
    new_dialog["utterances"] = []
    dialog_length = len(dialog["utterances"])

    for i, utt in enumerate(dialog["utterances"]):
        if utt['user']['user_type'] == 'human':
            new_dialog["utterances"].append(utt)
        elif utt['user']['user_type'] == 'bot':
            if 0 < i < dialog_length - 1 and is_bot_uttr_repeated_or_misheard(utt) and \
                    is_human_uttr_repeat_request_or_misheard(dialog["utterances"][i - 1]):
                new_dialog["utterances"] = new_dialog["utterances"][:-1]
            else:
                new_dialog["utterances"].append(utt)

    new_dialog["human_utterances"] = []
    new_dialog["bot_utterances"] = []

    for utt in new_dialog["utterances"]:
        if utt['user']['user_type'] == 'human':
            new_dialog["human_utterances"].append(deepcopy(utt))
        elif utt['user']['user_type'] == 'bot':
            new_dialog["bot_utterances"].append(deepcopy(utt))

    return new_dialog


def last_n_human_utt_dialog_formatter(dialog: Dict, last_n_utts: int, only_last_sentence: bool = False) -> List:
    """
    Args:
        dialog (Dict): full dialog state
        last_n_utts (int): how many last user utterances to take
        only_last_sentence (bool, optional): take only last sentence in each utterance. Defaults to False.
    """
    dialog = deepcopy(dialog)
    if len(dialog["human_utterances"]) <= last_n_utts and \
            not if_lets_chat_about_topic(dialog["utterances"][0]["text"].lower()):
        # in all cases when not particular topic, convert first phrase in the dialog to `hello!`
        if "sentseg" in dialog["human_utterances"][0]['annotations']:
            dialog["human_utterances"][0]['annotations']['sentseg']['punct_sent'] = "hello!"
            dialog["human_utterances"][0]['annotations']['sentseg']['segments'] = ["hello"]
        else:
            dialog["human_utterances"][0]['text'] = "hello"

    human_utts = []
    detected_intents = []
    for utt in dialog['human_utterances'][-last_n_utts:]:
        if "sentseg" in utt['annotations']:
            sentseg_ann = utt['annotations']['sentseg']
            if only_last_sentence:
                text = sentseg_ann['segments'][-1] if len(sentseg_ann['segments']) > 0 else ''
            else:
                text = sentseg_ann['punct_sent']
        else:
            text = utt["text"]
        human_utts += [text]
        detected_intents += [get_intents(utt, which="all")]
    return [{'sentences_batch': [human_utts], 'intents': [detected_intents]}]


def alice_formatter_dialog(dialog: Dict) -> List:
    # Used by: alice
    dialog = get_last_n_turns(dialog, bot_last_turns=4)
    dialog = remove_clarification_turns_from_dialog(dialog)
    return last_n_human_utt_dialog_formatter(dialog, last_n_utts=2, only_last_sentence=True)


def programy_formatter_dialog(dialog: Dict) -> List:
    # Used by: program_y, program_y_dangerous, program_y_wide
    dialog = get_last_n_turns(dialog, bot_last_turns=6)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = last_n_human_utt_dialog_formatter(dialog, last_n_utts=5)[0]
    sentences = dialog['sentences_batch'][0]
    intents = dialog['intents'][0]

    # modify sentences with yes/no intents to yes/no phrase
    # todo: sent may contain multiple sentence, logic here could be improved
    prioritized_intents = service_intents - {'yes', 'no'}
    for i, (sent, ints) in enumerate(zip(sentences, intents)):
        ints = set(ints)
        if '?' not in sent and len(ints & prioritized_intents) == 0:
            if 'yes' in ints:
                sentences[i] = 'yes.'
            elif 'no' in ints:
                sentences[i] = 'no.'
    return [{'sentences_batch': [sentences]}]


def eliza_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: eliza_formatter
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    history = []
    prev_human_utterance = None
    for utt in dialog['utterances']:
        if utt["user"]["user_type"] == "human":
            prev_human_utterance = utt['annotations'].get("spelling_preprocessing",
                                                          utt["text"])
        elif utt["user"]["user_type"] == "bot" and utt["active_skill"] == "eliza" and prev_human_utterance is not None:
            history.append(prev_human_utterance)
    last_utterance = dialog['human_utterances'][-1]['annotations'].get("spelling_preprocessing",
                                                                       dialog['human_utterances'][-1]["text"])
    return [{
        "last_utterance_batch": [last_utterance],
        "human_utterance_history_batch": [history],
    }]


def aiml_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: aiml_formatter
    return [{
        'states_batch': [{'user_id': dialog['human']['id']}],
        'utterances_batch': [dialog['utterances'][-1]['text']]
    }]


def cobot_qa_formatter_service(payload):
    # Used by: cobot_qa_formatter
    hyps = []
    for resp, conf in zip(payload[0], payload[1]):
        if len(resp) > 0 and conf > 0.:
            hyps.append({"text": resp, "confidence": conf})
    return hyps


def misheard_asr_formatter_service(payload):
    # Used by: misheard_asr_formatter
    hyps = []
    for resp, conf, ha, ba in zip(payload[0], payload[1], payload[2], payload[3]):
        if len(resp) > 0 and conf > 0:
            hyps.append({"text": resp, "confidence": conf, "human_attributes": ha, "bot_attributes": ba})
    return hyps


def replace_with_annotated_utterances(dialog, mode="punct_sent"):
    if mode == "punct_sent":
        for utt in dialog['utterances']:
            if "sentseg" in utt['annotations']:
                utt['text'] = utt['annotations']['sentseg']['punct_sent']
        for utt in dialog['human_utterances']:
            if "sentseg" in utt['annotations']:
                utt['text'] = utt['annotations']['sentseg']['punct_sent']
    elif mode == "segments":
        for utt in dialog['utterances']:
            if "sentseg" in utt['annotations']:
                utt['text'] = deepcopy(utt['annotations']['sentseg']['segments'])
            elif isinstance(utt['text'], str):
                utt['text'] = [utt['text']]
        for utt in dialog['human_utterances']:
            if "sentseg" in utt['annotations']:
                utt['text'] = deepcopy(utt['annotations']['sentseg']['segments'])
            elif isinstance(utt['text'], str):
                utt['text'] = [utt['text']]
        for utt in dialog['bot_utterances']:
            if "sentseg" in utt['annotations']:
                utt['text'] = deepcopy(utt['annotations']['sentseg']['segments'])
            elif isinstance(utt['text'], str):
                utt['text'] = [utt['text']]
    elif mode == "modified_sents":
        for utt in dialog['utterances']:
            if "sentrewrite" in utt['annotations']:
                utt['text'] = utt['annotations']['sentrewrite']['modified_sents'][-1]
            elif "sentseg" in utt['annotations']:
                utt['text'] = utt['annotations']['sentseg']['punct_sent']
        for utt in dialog['human_utterances']:
            if "sentrewrite" in utt['annotations']:
                utt['text'] = utt['annotations']['sentrewrite']['modified_sents'][-1]
            elif "sentseg" in utt['annotations']:
                utt['text'] = utt['annotations']['sentseg']['punct_sent']
    return dialog


def base_skill_selector_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: base_skill_selector_formatter
    dialog = get_last_n_turns(dialog, bot_last_turns=5)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    return [{"states_batch": [dialog]}]


def transfertransfo_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: transfertransfo_formatter
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    return [{
        'utterances_histories': [
            [utt['text'] for utt in dialog['utterances']]
        ],
        'personality': [dialog['bot']['persona']]
    }]


def convert_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: topicalchat_convert_retrieval
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    return [{
        'utterances_histories': [
            [utt['text'] for utt in dialog['utterances']]
        ],
        'personality': [dialog['bot']['persona']],
        'topics': [get_topics(dialog["utterances"][-1], which="cobot_topics")],
        'dialogact_topics': [get_topics(dialog["utterances"][-1], which="cobot_dialogact_topics")],
    }]


def personality_catcher_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: personality_catcher_formatter
    return [{'personality': [dialog['human_utterances'][-1]['annotations'].get(
        "spelling_preprocessing", dialog['human_utterances'][-1]['text'])]}]


def telegram_selector_formatter_in(dialog: Dict):
    return [dialog['human']['attributes']['active_skill']]


def personality_catcher_formatter_service(payload: List):
    # Used by: personality_catcher_formatter
    return [{
        'text': payload[0],
        'confidence': payload[1],
        'personality': payload[2],
        'bot_attributes': {'persona': payload[2]}
    }]


def cobot_classifiers_formatter_service(payload: List):
    # Used by: cobot_classifiers_formatter, sentiment_formatter
    if len(payload) == 3:
        return {"text": payload[0],
                "confidence": payload[1],
                "is_blacklisted": payload[2]}
    elif len(payload) == 2:
        return {"text": payload[0],
                "confidence": payload[1]}
    elif len(payload) == 1:
        return {"text": payload[0]}
    elif len(payload) == 0:
        return {"text": []}


def cobot_dialogact_formatter_service(payload: List):
    # Used by: cobot_dialogact_formatter
    return {"intents": payload[0],
            "topics": payload[1]}


def cobot_dialogact_intents_formatter_service(payload: List):
    return {"text": [j[0] for j in payload]}


def cobot_dialogact_topics_formatter_service(payload: List):
    return {"text": [j[0] for j in payload]}


def cobot_topics_formatter_service(payload: List):
    return {"text": [j[0] for j in payload]}


def cobot_formatter_dialog(dialog: Dict):
    # Used by: cobot_dialogact_formatter, cobot_classifiers_formatter
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="segments")
    utterances_histories = []
    for utt in dialog['utterances']:
        utterances_histories.append(utt['text'])
    return [{'utterances_histories': [utterances_histories]}]


def base_response_selector_formatter_service(payload: List):
    # Used by: base_response_selector_formatter
    if len(payload) == 3:
        return {"skill_name": payload[0], "text": payload[1], "confidence": payload[2]}
    elif len(payload) == 5:
        return {"skill_name": payload[0], "text": payload[1], "confidence": payload[2],
                "human_attributes": payload[3], "bot_attributes": payload[4]}


def sent_rewrite_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: sent_rewrite_formatter
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="segments")
    utterances_histories = []
    annotation_histories = []
    for utt in dialog['utterances']:
        annotation_histories.append(deepcopy(utt['annotations']))
        utterances_histories.append(utt['text'])
    return [{
        'utterances_histories': [utterances_histories],
        'annotation_histories': [annotation_histories]
    }]


def sent_rewrite_formatter_w_o_last_dialog(dialog: Dict) -> List[Dict]:
    dialog = get_last_n_turns(dialog, LAST_N_TURNS + 1)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="segments")
    utterances_histories = []
    annotation_histories = []
    for utt in dialog['utterances'][:-1]:
        annotation_histories.append(deepcopy(utt['annotations']))
        utterances_histories.append(utt['text'])
    return [{
        'utterances_histories': [utterances_histories],
        'annotation_histories': [annotation_histories]
    }]


def asr_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: asr_formatter
    return [{'speeches': [dialog['utterances'][-1].get('attributes', {}).get('speech', {})],
             'human_utterances': [dialog['human_utterances'][-3:]]}]


def last_utt_dialog(dialog: Dict) -> List[Dict]:
    # Used by: dp_toxic_formatter, sent_segm_formatter, tfidf_formatter, sentiment_classification
    return [{'sentences': [dialog['utterances'][-1]['text']]}]


def preproc_last_human_utt_dialog(dialog: Dict) -> List[Dict]:
    # Used by: sentseg over human uttrs
    return [{'sentences': [dialog['human_utterances'][-1]['annotations'].get("spelling_preprocessing",
                                                                             dialog['human_utterances'][-1]['text'])]}]


def last_bot_utt_dialog(dialog: Dict) -> List[Dict]:
    return [{'sentences': [dialog['bot_utterances'][-1]['text']]}]


def last_human_utt_nounphrases(dialog: Dict) -> List[Dict]:
    # Used by: comet_conceptnet_annotator
    return [{'nounphrases': [dialog['human_utterances'][-1]['annotations'].get('cobot_nounphrases', [])]}]


def hypotheses_list(dialog: Dict) -> List[Dict]:
    hypotheses = dialog["utterances"][-1]["hypotheses"]
    hypots = [h["text"] for h in hypotheses]
    return [{'sentences': hypots}]


def last_utt_and_history_dialog(dialog: Dict) -> List:
    # Used by: topicalchat retrieval skills
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    sent = dialog['human_utterances'][-1]['annotations'].get("spelling_preprocessing",
                                                             dialog['human_utterances'][-1]['text'])
    return [{
        'sentences': [sent],
        'utterances_histories': [[utt['text'] for utt in dialog['utterances']]]
    }]


def stop_formatter_dialog(dialog: Dict) -> List[Dict]:
    # Used by: stop annotator, conv eval annotator
    hypotheses = dialog["utterances"][-1]["hypotheses"]
    utts = []
    for h in hypotheses:
        tmp_utts = [m['text'] for m in dialog['utterances']]
        tmp_utts.append(h['text'])
        tmp_utts = ' [SEP] '.join([j for j in tmp_utts])
        utts.append(tmp_utts)
    return [{'dialogs': utts}]


def cobot_conv_eval_formatter_dialog(dialog: Dict) -> List[Dict]:
    dialog = get_last_n_turns(dialog, total_last_turns=4)
    payload = stop_formatter_dialog(dialog)
    # print(f"formatter {payload}", flush=True)
    return payload


def cobot_convers_evaluator_annotator_formatter(dialog: Dict) -> List[Dict]:
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    conv = dict()
    hypotheses = dialog["utterances"][-1]["hypotheses"]
    conv["hypotheses"] = [h["text"] for h in hypotheses]
    conv["currentUtterance"] = dialog["utterances"][-1]["text"]
    # cobot recommends to take 2 last utt for conversation evaluation service
    conv["pastUtterances"] = [uttr["text"] for uttr in dialog["human_utterances"]][-3:-1]
    conv["pastResponses"] = [uttr["text"] for uttr in dialog["bot_utterances"]][-2:]
    return [conv]


def dp_classes_formatter_service(payload: List):
    # Used by: dp_toxic_formatter
    return payload[0]


def base_formatter_service(payload: Dict) -> List[Dict]:
    '''
    Used by: dummy_skill_formatter, intent_responder_formatter, transfertransfo_formatter,
    aiml_formatter, alice_formatter, tfidf_formatter
    '''
    if len(payload[0]) > 0 and payload[1] > 0.:
        return [{"text": payload[0], "confidence": payload[1]}]
    else:
        return []


def simple_formatter_service(payload: List):
    '''
    Used by: punct_dialogs_formatter, intent_catcher_formatter, asr_formatter,
    sent_rewrite_formatter, sent_segm_formatter, base_skill_selector_formatter
    '''
    logging.info(f'answer {payload}')
    return payload


def utt_sentseg_punct_dialog(dialog: Dict):
    '''
    Used by: skill_with_attributes_formatter; punct_dialogs_formatter,
    dummy_skill_formatter, base_response_selector_formatter
    '''
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    return [{'dialogs': [dialog]}]


def utt_non_punct_dialog(dialog: Dict):
    '''
    Used by: book_skill
    '''
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    return [{'dialogs': [dialog]}]


def full_utt_sentseg_punct_dialog(dialog: Dict):
    '''
    Used ONLY by: greeting_skill (turns on only for first 10 turns)
    '''
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    return [{'dialogs': [dialog]}]


def full_history_dialog(dialog: Dict):
    '''
    Used ONLY by: response selector and greeting_skill (turns on only for first 10 turns)
    '''
    return [{'dialogs': [dialog]}]


def utt_sentrewrite_modified_last_dialog(dialog: Dict):
    # Used by: book_skill_formatter; misheard_asr_formatter, cobot_qa_formatter
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="modified_sents")
    return [{'dialogs': [dialog]}]


def utt_sentrewrite_modified_last_dialog_15_turns(dialog: Dict):
    # Used by: coronavirus
    dialog = get_last_n_turns(dialog, bot_last_turns=15)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="modified_sents")
    return [{'dialogs': [dialog]}]


def utt_sentrewrite_modified_last_dialog_emotion_skill(dialog: Dict):
    dialog = get_last_n_turns(dialog, bot_last_turns=25)
    dialog = remove_clarification_turns_from_dialog(dialog)
    dialog = replace_with_annotated_utterances(dialog, mode="modified_sents")
    return [{'dialogs': [dialog]}]


def skill_with_attributes_formatter_service(payload: Dict):
    """
    Formatter should use `"state_manager_method": "add_hypothesis"` in config!!!
    Because it returns list of hypothesis even if the payload is returned for one sample!

    Args:
        payload: if one sample, list of the following structure:
            (text, confidence, ^human_attributes, ^bot_attributes, attributes) [by ^ marked optional elements]
                if several hypothesis, list of lists of the above structure

    Returns:
        list of dictionaries of the following structure:
            {"text": text, "confidence": confidence_value,
             ^"human_attributes": {}, ^"bot_attributes": {},
             **attributes},
             by ^ marked optional elements
    """
    # Used by: book_skill_formatter, skill_with_attributes_formatter, news_skill, meta_script_skill, dummy_skill
    # deal with text & confidences
    if isinstance(payload[0], list) and isinstance(payload[1], list):
        # several hypotheses from this skill
        result = []
        for hyp in zip(*payload):
            if len(hyp[0]) > 0 and hyp[1] > 0.:
                full_hyp = {"text": hyp[0], "confidence": hyp[1]}
                if len(payload) >= 4:
                    # have human and bot attributes in hyps
                    full_hyp["human_attributes"] = hyp[2]
                    full_hyp["bot_attributes"] = hyp[3]
                if len(payload) == 3 or len(payload) == 5:
                    # have also attributes in hyps
                    assert isinstance(hyp[-1], dict), "Attribute is a dictionary"
                    for key in hyp[-1]:
                        full_hyp[key] = hyp[-1][key]
                result += [full_hyp]
    else:
        # only one hypotheses from this skill
        if len(payload[0]) > 0 and payload[1] > 0.:
            result = [{"text": payload[0],
                       "confidence": payload[1]}]
            if len(payload) >= 4:
                # have human and bot attributes in hyps
                result[0]["human_attributes"] = payload[2]
                result[0]["bot_attributes"] = payload[3]
            if len(payload) == 3 or len(payload) == 5:
                # have also attributes in hyps
                assert isinstance(payload[-1], dict), "Attribute is a dictionary"
                for key in payload[-1]:
                    result[0][key] = payload[-1][key]
        else:
            result = []

    return result


def last_utt_sentseg_punct_dialog(dialog: Dict):
    # Used by: attitude_formatter, sentiment_formatter
    if "sentseg" in dialog['utterances'][-1]['annotations']:
        return [{'sentences': [dialog['utterances'][-1]['annotations']['sentseg']['punct_sent']]}]
    else:
        return [{'sentences': [dialog['utterances'][-1]['text']]}]


def last_utt_sentseg_segments_dialog(dialog: Dict):
    # Used by: intent_catcher_formatter
    if "sentseg" in dialog['utterances'][-1]['annotations']:
        return [{'sentences': [dialog['utterances'][-1]['annotations']['sentseg']['segments']]}]
    else:
        segments = [dialog['utterances'][-1]['text']]
        return [{'sentences': [segments]}]


def ner_formatter_dialog(dialog: Dict):
    # Used by: ner_formatter
    if "sentseg" in dialog['human_utterances'][-1]['annotations']:
        return [{'last_utterances': [dialog['human_utterances'][-1]['annotations']['sentseg']['segments']]}]
    else:
        segments = [dialog['human_utterances'][-1]['text']]
        return [{'last_utterances': [segments]}]


def ner_formatter_last_bot_dialog(dialog: Dict):
    if "sentseg" in dialog['bot_utterances'][-1]['annotations']:
        return [{'last_utterances': [dialog['bot_utterances'][-1]['annotations']['sentseg']['segments']]}]
    else:
        segments = [dialog['bot_utterances'][-1]['text']]
        return [{'last_utterances': [segments]}]


# def reddit_ner_formatter_dialog(dialog: Dict):
#     # Used by: reddit_ner_skill
#     dialog = get_last_n_turns(dialog)
#     dialog = remove_clarification_turns_from_dialog(dialog)
#     return [
#         {
#             'sentiment': [dialog['utterances'][-1]['annotations']['sentiment_classification']],
#             'intent': [dialog['utterances'][-1]['annotations']['intent_catcher']],
#             'ner': [dialog['utterances'][-1]['annotations']['ner']],
#             'continuation': [0 if len(dialog['utterances']) < 2
#                              else int(dialog['utterances'][-2]['active_skill'] == 'reddit_ner_skill')]
#         }
#     ]
def wp_formatter_dialog(dialog: Dict):
    # Used by: wiki_parser annotator
    entity_ids_batch, _ = dialog['human_utterances'][-1]['annotations'].get('entity_linking', [[], []])
    input_entity_ids = []
    if entity_ids_batch:
        for entity_ids_list in entity_ids_batch:
            if entity_ids_list:
                input_entity_ids.append(entity_ids_list[0])
    input_entity_ids = list(set(input_entity_ids))
    parser_info = ["find_top_triplets"]
    if not input_entity_ids:
        input_entity_ids = [""]
    return [
        {
            'parser_info': parser_info,
            'query': [input_entity_ids]
        }
    ]


def el_formatter_dialog(dialog: Dict):
    # Used by: entity_linking annotator
    ner_output = dialog['human_utterances'][-1]['annotations']['ner']
    nounphrases = dialog['human_utterances'][-1]['annotations'].get('cobot_nounphrases', [])
    entity_substr = [[entity["text"] for entity in entities] for entities in ner_output]

    if "sentseg" in dialog['human_utterances'][-1]['annotations']:
        last_human_utterance_text = dialog['human_utterances'][-1]['annotations']['sentseg']['punct_sent']
    else:
        last_human_utterance_text = dialog['human_utterances'][-1]['text']

    context = [last_human_utterance_text for _ in entity_substr]
    template = ['' for _ in entity_substr]
    if nounphrases:
        entity_substr.append(nounphrases)
        context.append(last_human_utterance_text)
        template.append('')

    return [
        {
            'entity_substr': entity_substr,
            'template': template,
            'context': context
        }
    ]


def kbqa_formatter_dialog(dialog: Dict):
    # Used by: kbqa annotator
    annotations = dialog['human_utterances'][-1]['annotations']
    if "sentseg" in annotations:
        if "segments" in annotations['sentseg']:
            sentences = deepcopy(annotations['sentseg']['segments'])
        else:
            sentences = [deepcopy(annotations['sentseg']['punct_sent'])]
    else:
        sentences = [deepcopy(dialog['human_utterances'][-1]['text'])]
    ner_output = annotations['ner']
    entity_substr = [[entity["text"] for entity in entities] for entities in ner_output]
    nounphrases = annotations.get('cobot_nounphrases', [])
    entities = []
    for n, entities_list in enumerate(entity_substr):
        if entities_list:
            entities.append([entities_list[0]])
        elif nounphrases and len(nounphrases) > n:
            entities.append(nounphrases[n])
        else:
            entities.append([])
    if not entities:
        entities = [[] for _ in sentences]
    entities = entities[:len(sentences)]

    return [{'x_init': sentences,
             'entities': entities}]


def odqa_formatter_dialog(dialog: Dict):
    # Used by: odqa annotator
    if "sentseg" in dialog['human_utterances'][-1]['annotations']:
        last_human_utterance_text = dialog['human_utterances'][-1]['annotations']['sentseg']['punct_sent']
    else:
        last_human_utterance_text = dialog['human_utterances'][-1]['text']

    sentences = [last_human_utterance_text]
    nounphrases = [dialog['human_utterances'][-1]['annotations'].get('cobot_nounphrases', [])]
    return [{'question_raw': sentences, "entity_substr": nounphrases}]


def short_story_formatter_dialog(dialog: Dict):
    # Used by: short_story_skill
    return [
        {
            'intents': dialog['human_utterances'][-1]['annotations'].get('intent_catcher', {}),
            'human_sentence': dialog['human_utterances'][-1]['annotations'].get("spelling_preprocessing",
                                                                                dialog['human_utterances'][-1]['text']),
            'state': dialog["bot"]["attributes"].get("short_story_skill_attributes", {})
        }
    ]


def intent_responder_formatter_dialog(dialog: Dict):
    # Used by: intent_responder
    dialog = get_last_n_turns(dialog)
    dialog = remove_clarification_turns_from_dialog(dialog)
    intents = list(dialog['utterances'][-1]['annotations']['intent_catcher'].keys())
    called_intents = {intent: False for intent in intents}
    for utt in dialog['human_utterances'][-5:-1]:
        called = [intent for intent, value in utt['annotations'].get('intent_catcher', {}).items() if value['detected']]
        for intent in called:
            called_intents[intent] = True
    dialog['called_intents'] = called_intents
    dialog["utterances"] = dialog["utterances"][-(LAST_N_TURNS * 2 + 1):]
    for utt in dialog['utterances']:
        if "sentseg" in utt['annotations']:
            utt['text'] = utt['annotations']['sentseg']['punct_sent']
    return [{'dialogs': [dialog]}]


def attitude_formatter_service(payload: Dict):
    # Used by: attitude_formatter
    payload = payload[0]
    if len(payload) == 2:
        return {"text": payload[0],
                "confidence": payload[1]}
    elif len(payload) == 1:
        return {"text": payload[0]}
    elif len(payload) == 0:
        return {"text": []}


def dialog_breakdown_formatter(dialog: Dict) -> List[Dict]:
    # Used by: dialog_breakdown
    dialog = get_last_n_turns(dialog, bot_last_turns=2)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    context = " ".join([uttr["text"] for uttr in dialog['utterances'][-4:-1]])
    return [{'context': [context],
             "curr_utterance": [dialog['utterances'][-1]["text"]]
             }]


def hypotheses_list_for_dialog_breakdown(dialog: Dict) -> List[Dict]:
    # Used by: dialog_breakdown
    dialog = get_last_n_turns(dialog, bot_last_turns=2)
    dialog = replace_with_annotated_utterances(dialog, mode="punct_sent")
    context = " ".join([uttr["text"] for uttr in dialog['utterances'][-3:]])
    hyps = {"context": [], "curr_utterance": []}
    for hyp in dialog["utterances"][-1]["hypotheses"]:
        hyps["context"].append(context)
        hyps["curr_utterance"].append(hyp["text"])
    return [hyps]

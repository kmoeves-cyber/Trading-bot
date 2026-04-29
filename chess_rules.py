import random


class RuleEffect:
    def __init__(self, tag, params=None):
        self.tag = tag
        self.params = params or {}

    def to_dict(self):
        return {'tag': self.tag, 'params': self.params}

    @staticmethod
    def from_dict(d):
        return RuleEffect(d['tag'], d.get('params', {}))


class DynamicRule:
    def __init__(self, id_, name, description, effects, duration=8, emoji='⚡',
                 instant=False):
        self.id = id_
        self.name = name
        self.description = description
        self.effects = effects  # list[RuleEffect]
        self.duration = duration  # half-turns; 0 = instant board mutation
        self.emoji = emoji
        self.instant = instant  # if True, mutate board immediately on trigger

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'effects': [e.to_dict() for e in self.effects],
            'duration': self.duration,
            'emoji': self.emoji,
            'instant': self.instant,
        }


# ── Rule catalog ──────────────────────────────────────────────────────────────

RULE_CATALOG = [
    DynamicRule(
        'pawns_backward', 'Reverse Pawns',
        'Pawns may now move backward as well as forward.',
        [RuleEffect('pawns_backward')], duration=8, emoji='↩️'
    ),
    DynamicRule(
        'king_queen_move', 'Royal Power',
        'Kings can move like queens — anywhere in a straight line.',
        [RuleEffect('king_queen_move')], duration=8, emoji='👑'
    ),
    DynamicRule(
        'mirror_board', 'Mirror World',
        'The board is displayed from both players\' opposite perspective.',
        [RuleEffect('mirror_board')], duration=8, emoji='🪞'
    ),
    DynamicRule(
        'double_move', 'Double Time',
        'Each player makes 2 moves per turn instead of 1.',
        [RuleEffect('double_move')], duration=8, emoji='⏩'
    ),
    DynamicRule(
        'early_promote', 'Speed Promotion',
        'Pawns promote to Queen the moment they cross the midpoint (rank 5).',
        [RuleEffect('early_promote')], duration=8, emoji='🚀'
    ),
    DynamicRule(
        'rooks_diagonal', 'Rook-Bishop Fusion',
        'Rooks can now also slide diagonally like bishops.',
        [RuleEffect('rooks_diagonal')], duration=8, emoji='✖️'
    ),
    DynamicRule(
        'bishops_straight', 'Bishop-Rook Fusion',
        'Bishops can now also slide straight like rooks.',
        [RuleEffect('bishops_straight')], duration=8, emoji='➕'
    ),
    DynamicRule(
        'knights_rook', 'Knight Charge',
        'Knights abandon their L-shape and now move like rooks.',
        [RuleEffect('knights_rook')], duration=8, emoji='🏇'
    ),
    DynamicRule(
        'friendly_fire', 'Friendly Fire',
        'Pieces may capture their own teammates. Be careful!',
        [RuleEffect('friendly_fire')], duration=8, emoji='💥'
    ),
    DynamicRule(
        'forced_capture', 'Blood Rule',
        'If any capture is possible, you MUST take it. No retreat.',
        [RuleEffect('forced_capture')], duration=8, emoji='🩸'
    ),
    DynamicRule(
        'pawns_knight', 'Pawn Uprising',
        'Pawns have learned the knight\'s L-shaped leap.',
        [RuleEffect('pawns_knight')], duration=8, emoji='♞'
    ),
    DynamicRule(
        'all_jump', 'Leap of Faith',
        'All pieces can jump over any other piece this round.',
        [RuleEffect('all_jump')], duration=8, emoji='🦘'
    ),
    DynamicRule(
        'knighted_on_jump', 'Knight Fever',
        'Any piece that jumps over 3 or more pieces in one move becomes a knight.',
        [RuleEffect('all_jump'), RuleEffect('knighted_on_jump')], duration=8, emoji='⚔️'
    ),
    DynamicRule(
        'swap_rooks_bishops', 'Rook-Bishop Swap',
        'All rooks instantly become bishops, and all bishops become rooks!',
        [RuleEffect('swap_types', {'from_type': 'R', 'to_type': 'B'}),
         RuleEffect('swap_types', {'from_type': 'B', 'to_type': 'R'})],
        duration=0, emoji='🔄', instant=True
    ),
    DynamicRule(
        'swap_queens_knights', 'Queen-Knight Swap',
        'Queens and knights swap their identities across the whole board!',
        [RuleEffect('swap_types', {'from_type': 'Q', 'to_type': 'N'}),
         RuleEffect('swap_types', {'from_type': 'N', 'to_type': 'Q'})],
        duration=0, emoji='🃏', instant=True
    ),
    DynamicRule(
        'shuffle_white', 'White Chaos',
        'All white pieces are teleported to random squares!',
        [RuleEffect('shuffle', {'color': 'w'})],
        duration=0, emoji='🌀', instant=True
    ),
    DynamicRule(
        'shuffle_black', 'Black Chaos',
        'All black pieces are teleported to random squares!',
        [RuleEffect('shuffle', {'color': 'b'})],
        duration=0, emoji='🌪️', instant=True
    ),
]


class RulesEngine:
    def __init__(self):
        self._catalog = {r.id: r for r in RULE_CATALOG}

    def pick_random_rule(self, exclude_ids=None):
        exclude_ids = set(exclude_ids or [])
        available = [r for r in RULE_CATALOG if r.id not in exclude_ids]
        if not available:
            available = RULE_CATALOG[:]
        return random.choice(available)

    def tick(self, half_turn, active_rules):
        """
        Called after each completed half-turn.
        Decrements remaining_turns; removes expired rules.
        At multiples of 4, picks and adds a new rule.
        Returns (updated_active_rules, new_rule_dict_or_None).
        """
        updated = []
        for rd in active_rules:
            if rd['duration'] == 0:
                continue  # instant rules are never stored in active list
            rd = dict(rd)  # shallow copy
            rd['remaining_turns'] -= 1
            if rd['remaining_turns'] > 0:
                updated.append(rd)

        new_rule = None
        if half_turn > 0 and half_turn % 4 == 0:
            active_ids = [r['id'] for r in updated]
            rule = self.pick_random_rule(exclude_ids=active_ids)
            new_rule = rule.to_dict()
            if not rule.instant:
                rule_state = dict(new_rule)
                rule_state['remaining_turns'] = rule.duration
                updated.append(rule_state)

        return updated, new_rule

    def get_effects_set(self, active_rules):
        """Returns a flat set of all active effect tags for O(1) lookup."""
        effects = set()
        for rd in active_rules:
            for e in rd.get('effects', []):
                effects.add(e['tag'])
        return effects

    def apply_instant_mutations(self, board, rule_dict):
        """Apply instant board-mutation rules immediately."""
        for effect in rule_dict.get('effects', []):
            tag = effect['tag']
            params = effect.get('params', {})
            if tag == 'swap_types':
                self._swap_types(board, params['from_type'], params['to_type'])
            elif tag == 'shuffle':
                self._shuffle_color(board, params['color'])

    def _swap_types(self, board, from_type, to_type):
        # Collect and apply simultaneously to avoid double-swap
        targets_from = []
        targets_to = []
        for r in range(8):
            for c in range(8):
                p = board.grid[r][c]
                if p:
                    if p.type == from_type:
                        targets_from.append((r, c))
                    elif p.type == to_type:
                        targets_to.append((r, c))
        for r, c in targets_from:
            board.grid[r][c].type = to_type
        for r, c in targets_to:
            board.grid[r][c].type = from_type

    def _shuffle_color(self, board, color, max_attempts=20):
        positions = []
        pieces = []
        for r in range(8):
            for c in range(8):
                p = board.grid[r][c]
                if p and p.color == color:
                    positions.append((r, c))
                    pieces.append(p)

        # Try up to max_attempts shuffles; ensure neither king ends in check
        from chess_engine import ChessEngine
        engine = ChessEngine()
        for _ in range(max_attempts):
            shuffled = positions[:]
            random.shuffle(shuffled)

            # Assign pieces to shuffled positions
            for (r, c), piece in zip(shuffled, pieces):
                board.set(r, c, piece)
            # Clear original positions that weren't reused
            original = set(positions)
            used = set(shuffled)
            for r, c in original - used:
                board.set(r, c, None)

            # Verify kings are not immediately in check
            if not engine.is_in_check(board, 'w', set()) and \
               not engine.is_in_check(board, 'b', set()):
                return

        # If all attempts fail, restore original positions
        for (r, c), piece in zip(positions, pieces):
            board.set(r, c, piece)

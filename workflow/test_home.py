from datetime import date, time
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import Profile, AnnualBalance, Document
from .home import quick_form, progress_stages
from .services import save_document, act_on_document


class HomeWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        for key in ['owner', 'reviewer', 'approver', 'other', 'admin']:
            user = User.objects.create_user(key, first_name=key, password='1234')
            Profile.objects.create(user=user, department='개발팀', rank='대리', approved=True,
                                   manage_system=key == 'admin')
            setattr(cls, key, user)
        AnnualBalance.objects.create(user=cls.owner, year=2026, total=15, used=0, grant_initialized=True)

    def payload(self, kind='leave', intent='submit'):
        prefix = f'home_{kind}-'
        fields = {'reviewer': self.reviewer.pk, 'approver': self.approver.pk,
                  'reviewer_department': '개발팀', 'approver_department': '개발팀',
                  'reason': '홈 작성 시험'}
        if kind == 'leave':
            fields.update(leave_type='annual', start_date='2026-10-19', end_date='2026-10-19')
        else:
            fields.update(product='A4 용지', quantity='2', unit_price='1200.25', url='https://example.com/a4')
        return {'home_kind': kind, 'intent': intent, **{prefix+k: v for k, v in fields.items()}}

    def test_home_links_open_correct_forms_with_independent_department_pickers(self):
        for kind in ['leave', 'office']:
            form = quick_form(self.owner, kind, date(2026, 10, 14))
            self.assertEqual(form.fields['reviewer_department'].widget.attrs['data-person-field'], f'id_home_{kind}-reviewer')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('dashboard'))
        for kind in ['leave', 'office']:
            self.assertContains(response, f'{reverse("compose")}?kind={kind}')
            form_response = self.client.get(reverse('compose'), {'kind': kind})
            self.assertEqual(form_response.context['form']['kind'].value(), kind)
            self.assertNotIn(self.admin.pk, form_response.context['form'].fields['reviewer'].queryset.values_list('pk', flat=True))
        self.assertContains(response, '전체 문서 검색')
        self.assertContains(response, 'workspace.css')

    @patch('workflow.context.timezone.localdate', return_value=date(2026, 10, 15))
    def test_home_balance_uses_current_employee_and_year(self, _today):
        AnnualBalance.objects.filter(user=self.owner, year=2026).update(used=Decimal('2.25'))
        AnnualBalance.objects.create(user=self.owner, year=2025, total=99, used=0, grant_initialized=True)
        AnnualBalance.objects.create(user=self.other, year=2026, total=23, used=1, grant_initialized=True)
        for user, values in [(self.owner, ('15', '2.25', '12.75')), (self.other, ('23', '1', '22'))]:
            self.client.force_login(user)
            response = self.client.get(reverse('dashboard'))
            for label, value in zip(['총연차', '사용연차', '잔여연차'], values):
                self.assertContains(response, f'aria-label="{label} {value}일"')
            self.assertNotContains(response, 'aria-label="총연차 99일"')

    @patch('workflow.context.timezone.localdate', return_value=date(2026, 10, 15))
    def test_home_balance_reflects_manual_changes_zero_and_negative_remaining(self, _today):
        self.client.force_login(self.owner)
        for used, expected in [('16.25', '-1.25'), ('15', '0')]:
            AnnualBalance.objects.filter(user=self.owner, year=2026).update(used=used)
            response = self.client.get(reverse('dashboard'))
            self.assertContains(response, f'aria-label="잔여연차 {expected}일"')
            self.assertNotContains(response, '연차가 아직 등록되지 않았습니다.')

    @patch('workflow.context.timezone.localdate', return_value=date(2026, 10, 15))
    def test_home_unregistered_balance_is_not_presented_as_zero_entitlement(self, _today):
        self.client.force_login(self.other)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '연차가 아직 등록되지 않았습니다.')
        self.assertNotContains(response, 'aria-label="총연차 0일"')

    def test_home_kind_filter_and_counts_are_limited_to_submitted_own_documents(self):
        office = save_document(Document(owner=self.owner, kind='office', product='내 사무용품', quantity=1,
            unit_price=10, url='https://example.com', reviewer=self.reviewer, approver=self.approver), self.owner, submit=True)
        stock = save_document(Document(owner=self.owner, kind='stock', product='내 재고요청', quantity=1,
            reviewer=self.reviewer), self.owner, submit=True)
        save_document(Document(owner=self.other, kind='office', product='타인 비공개 품목', quantity=1,
            unit_price=10, url='https://example.com', reviewer=self.reviewer, approver=self.approver), self.other, submit=True)
        for status in ['draft', 'deleted']:
            Document.objects.create(owner=self.owner, kind='office', status=status, product='숨긴 품목')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('dashboard'), {'home_kind': 'office'})
        self.assertEqual(list(response.context['documents']), [office])
        self.assertEqual({row['key']: row['count'] for row in response.context['home_categories']},
                         {'all': 2, 'leave': 0, 'office': 1, 'stock': 1})
        self.assertNotContains(response, '타인 비공개 품목')
        self.assertNotContains(response, '숨긴 품목')
        response = self.client.get(reverse('dashboard'), {'home_kind': 'stock'})
        self.assertEqual(list(response.context['documents']), [stock])
        response = self.client.get(reverse('dashboard'), {'home_kind': 'leave'})
        self.assertContains(response, '해당 종류의 문서가 없습니다')
        self.assertEqual(list(response.context['documents']), [])

    def test_unknown_home_kind_safely_defaults_to_all(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('dashboard'), {'home_kind': 'not-a-document-kind'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['home_kind'], 'all')
        self.assertContains(response, '아직 작성한 문서가 없습니다')

    def test_home_leave_submission_reuses_workflow_and_does_not_charge_early(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('compose'), self.payload())
        self.assertEqual(response.status_code, 302)
        doc = Document.objects.get()
        self.assertEqual((doc.owner, doc.kind, doc.status), (self.owner, 'leave', 'review'))
        self.assertEqual(AnnualBalance.objects.get(user=self.owner, year=2026).used, 0)

    def test_home_office_price_draft_and_submit(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('compose'), self.payload('office', 'draft')).status_code, 302)
        draft = Document.objects.get(status='draft')
        self.assertIsNone(draft.number)
        self.assertEqual(self.client.post(reverse('compose'), self.payload('office')).status_code, 302)
        doc = Document.objects.get(status='review')
        self.assertEqual(doc.total_price, Decimal('2400.50'))
        self.assertEqual(doc.recipient, self.owner)

    def test_home_invalid_fields_show_full_form_without_saving_and_admin_cannot_be_selected(self):
        self.client.force_login(self.owner)
        payload = self.payload('office')
        payload['home_office-url'] = ''
        response = self.client.post(reverse('compose'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.exists())
        self.assertContains(response, 'id="compose-form"')
        payload = self.payload()
        payload['home_leave-reviewer'] = self.admin.pk
        self.client.post(reverse('compose'), payload)
        self.assertFalse(Document.objects.exists())

    def test_global_search_respects_document_visibility_and_keeps_query_in_tabs(self):
        for owner in [self.owner, self.other]:
            save_document(Document(owner=owner, kind='office', product='shared needle', quantity=1,
                unit_price=10, url='https://example.com', reviewer=self.reviewer, approver=self.approver), owner, submit=True)
        self.client.force_login(self.owner)
        response = self.client.get(reverse('documents'), {'mode': 'search', 'q': 'shared needle'})
        self.assertEqual(response.context['document_count'], 1)
        self.assertEqual(response.context['documents'][0].owner, self.owner)
        self.assertContains(response, 'q=shared%20needle')
        self.assertEqual(self.client.get(reverse('documents'), {'mode': 'search'}).context['document_count'], 0)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse('documents'), {'mode': 'search', 'q': 'shared needle'}).context['document_count'], 2)

    def test_progress_stages_include_stock_ordering_and_do_not_show_cancelled_as_pending(self):
        doc = save_document(Document(owner=self.owner, kind='stock', product='매뉴얼', quantity=1,
                                     reviewer=self.reviewer), self.owner, submit=True)
        self.assertEqual([step['label'] for step in progress_stages(doc)], ['기안', '검토', '발주', '입고'])
        doc = act_on_document(doc.pk, self.reviewer, 'review')
        self.assertEqual(next(step['label'] for step in progress_stages(doc) if step.get('current')), '발주')
        doc = act_on_document(doc.pk, self.reviewer, 'cancel_review', '취소')
        self.assertFalse(any(step.get('current') for step in progress_stages(doc)))

    def test_search_finds_displayed_leave_type_without_exposing_other_employee_documents(self):
        for owner in [self.owner, self.other]:
            save_document(Document(owner=owner, reviewer=self.reviewer, approver=self.approver, kind='leave',
                leave_type='outing', start_date=date(2026, 10, 19), end_date=date(2026, 10, 19),
                start_time=time(9), end_time=time(10), reason='개인 일정'), owner, submit=True)
        self.client.force_login(self.owner)
        response = self.client.get(reverse('documents'), {'mode': 'search', 'q': '외출'})
        self.assertEqual(response.context['document_count'], 1)
        self.assertEqual(response.context['documents'][0].owner, self.owner)

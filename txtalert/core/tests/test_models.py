from django.test import TestCase
from django.contrib.auth.models import Group
from django.utils import timezone
from datetime import datetime
from txtalert.core.models import *
from mock import patch


class PermissionsTestCase(TestCase):
    fixtures = ['patients', 'clinics', 'visits']

    def setUp(self):
        pass

    def tearDown(self):
        pass

        # def test_msisdn_access(self):
        #     assert False
        #
        # def test_patient_access(self):
        #     assert False
        #
        # def test_clinic_access(self):
        #     assert False
        #
        # def test_visit_acess(self):
        #     assert False


class ModelTestCase(TestCase):
    fixtures = ['patients', 'clinics', 'visits']

    def test_patient_soft_delete(self):
        patient = Patient.objects.all()[0]
        patient.delete()
        # regular get fails because it is flagged as deleted
        self.assertRaises(
            Patient.DoesNotExist,
            Patient.objects.get,
            pk=patient.pk
        )
        # the all_objects manager however, should expose it
        self.assertEquals(patient, Patient.all_objects.get(pk=patient.pk))

    def test_patient_clinics(self):
        patient = Patient.objects.filter(last_clinic=None)[0]
        self.assertEquals(patient.get_last_clinic(), None)
        self.assertEquals(patient.clinics(), set([]))

        visit = patient.visit_set.create(
            clinic=Clinic.objects.all()[0],
            date=timezone.now(),
            status='s'
        )

        self.assertTrue(visit.clinic in patient.clinics())
        self.assertEquals(visit.clinic, patient.get_last_clinic())


from django.test import TestCase
from txtalert.apps.gateway.models import PleaseCallMe as GatewayPleaseCallMe
from txtalert.core.models import PleaseCallMe, Patient, Clinic, MSISDN
from datetime import timedelta


class PleaseCallMeTestCase(TestCase):
    fixtures = ['patients', 'clinics', 'visits']

    def setUp(self):
        # use dummy gateway
        from txtalert.apps import gateway

        gateway.load_backend('txtalert.apps.gateway.backends.dummy')

        self.user = User.objects.get(username="kumbu")

        self.patient = Patient.objects.all()[0]
        self.patient.save()  # save to specify the active_msisdn

        # create a number of visits for this patient at a clinic
        for i in range(0, 10):
            self.patient.visit_set.create(
                clinic=Clinic.objects.get(name='Test Clinic'),
                date=timezone.now() + timedelta(days=i),
                status='s'
            )

        self.assertTrue(self.patient.visit_set.all())
        self.assertTrue(self.patient.active_msisdn)  # make sure that actually worked
        self.assertTrue(self.patient.get_last_clinic())
        self.assertTrue(self.patient.last_clinic)

    def tearDown(self):
        pass

    def test_please_call_me_from_gateway(self):
        # we should have non registered
        self.assertEquals(PleaseCallMe.objects.count(), 0)

        gpcm = GatewayPleaseCallMe.objects.create(
            sms_id='sms_id',
            sender_msisdn=self.patient.active_msisdn.msisdn,
            recipient_msisdn='27123456789',
            user=self.user,
            message='Please Call Me',
        )

        # we should have one registered through the signals
        self.assertEquals(PleaseCallMe.objects.count(), 1)
        pcm = PleaseCallMe.objects.latest('timestamp')
        self.assertEquals(pcm.msisdn, self.patient.active_msisdn)
        self.assertEquals(pcm.clinic, self.patient.last_clinic)
        self.assertEquals(pcm.message, gpcm.message)

    def test_please_call_me_from_therapyedge(self):
        pcm = PleaseCallMe.objects.create(
            msisdn=self.patient.active_msisdn,
            timestamp=timezone.now(),
            user=self.user,
        )
        # the signals should track the clinic for this pcm if it hasn't
        # been specified automatically yet
        self.assertEquals(pcm.clinic, Clinic.objects.get(name='Test Clinic'))

    def test_pcm_for_nonexistent_msisdn(self):
        # verify this nr doesn't exist in the db
        self.assertRaises(
            MSISDN.DoesNotExist,
            MSISDN.objects.get,
            msisdn='27123456789'
        )
        # this shouldn't raise an error, it should fail silently leaving
        # message in the log file
        GatewayPleaseCallMe.objects.create(
            sms_id='sms_id',
            sender_msisdn='27123456789',  # this shouldn't exist in the db
            user=self.user,
        )

    def test_multiple_patients_for_one_msisdn(self):
        msisdn = MSISDN.objects.create(msisdn='27123456789')
        for i in range(0, 2):
            Patient.objects.create(
                active_msisdn=msisdn,
                owner=self.user,
                te_id='06-%s2345' % i,
                age=23
            )
        # we have two patients for the same msisdn
        self.assertEquals(
            Patient.objects.filter(active_msisdn=msisdn).count(),
            2
        )
        # this shouldn't raise an error, it should fail silently leaving
        # message in the log file
        GatewayPleaseCallMe.objects.create(
            sms_id='sms_id',
            sender_msisdn=msisdn.msisdn,
            user=self.user,
        )

    def test_sloppy_get_or_create_possible_msisdn(self):
        MSISDN.objects.create(msisdn='27123456121')
        from txtalert.core.signals import sloppy_get_or_create_possible_msisdn

        self.assertEquals(
            sloppy_get_or_create_possible_msisdn('121').msisdn,
            '121'
        )
        self.assertEquals(
            sloppy_get_or_create_possible_msisdn('0123456121').msisdn,
            '27123456121'
        )
        self.assertEquals(
            sloppy_get_or_create_possible_msisdn('27123456121').msisdn,
            '27123456121'
        )
        self.assertEquals(
            sloppy_get_or_create_possible_msisdn('+27123456121').msisdn,
            '27123456121'
        )


class ClinicMappingTestCase(TestCase):
    fixtures = ['clinics']

    def test_clinic_mapping(self):
        clinic = Clinic.objects.get(name='Test Clinic')
        ClinicNameMapping.objects.create(
            wrhi_clinic_name='Test_Clinic_External',
            clinic=clinic)

        from txtalert.core.wrhi_automation import map_clinic

        db_clinic = map_clinic('Test_Clinic_External')

        self.assertEquals(clinic.pk, db_clinic.pk)


class ImportPatientsTestCase(TestCase):
    fixtures = ['clinics', 'users']

    def test_patient_import(self):
        from mock import patch

        clinic = Clinic.objects.get(name='Test Clinic')
        ClinicNameMapping.objects.create(
            wrhi_clinic_name='Test_Clinic_External',
            clinic=clinic)

        with patch('txtalert.core.wrhi_automation.fetch_patient_data') as mock_fetch_patient_data:
            from txtalert.core.wrhi_automation import import_patients

            payload = [
                {
                    'Facility_name': 'Test_Clinic_External',
                    'Patients': [
                        {
                            'Ptd_No': 'MV00001',
                            'File_No': 'MC681124',
                            'Cellphone_number': '794046170'
                        },
                        {
                            'Ptd_No': 'MV00002',
                            'File_No': '141',
                            'Cellphone_number': '714946377'
                        },
                        {
                            'Ptd_No': 'MV00003',
                            'File_No': 'MC701231',
                            'Cellphone_number': '820644417'
                        }
                    ]}
            ]

            mock_fetch_patient_data.return_value = payload
            import_patients('test')

            p1 = Patient.objects.get(te_id='MV00001')
            p2 = Patient.objects.get(te_id='MV00002')
            p3 = Patient.objects.get(te_id='MV00003')

            # user p1 should have one mobile
            self.assertEquals(len(p1.msisdns.all()), 1)

            MSISDN.objects.get(msisdn='794046170')
            MSISDN.objects.get(msisdn='714946377')
            MSISDN.objects.get(msisdn='820644417')

            p2.delete()
            p3.delete()

            payload = [
                {
                    'Facility_name': 'Test_Clinic_External',
                    'Patients': [
                        {
                            'Ptd_No': 'MV00001',
                            'File_No': 'MC681124',
                            'Cellphone_number': '794046170/794046171'
                        },
                        {
                            'Ptd_No': 'MV00002',
                            'File_No': '141',
                            'Cellphone_number': '714946377'
                        },
                        {
                            'Ptd_No': 'MV00003',
                            'File_No': 'MC701231',
                            'Cellphone_number': '820644417'
                        }
                    ]}
            ]

            mock_fetch_patient_data.return_value = payload
            import_patients('test')

            p1 = Patient.objects.get(te_id='MV00001')

            # Deleted patients should not be added
            self.assertRaises(
                Patient.DoesNotExist,
                Patient.objects.get,
                te_id='MV00002'
            )

            self.assertRaises(
                Patient.DoesNotExist,
                Patient.objects.get,
                te_id='MV00003'
            )

            # user p1 should have two mobiles
            self.assertEquals(len(p1.msisdns.all()), 2)

            MSISDN.objects.get(msisdn='794046170')
            MSISDN.objects.get(msisdn='794046171')
            MSISDN.objects.get(msisdn='714946377')
            MSISDN.objects.get(msisdn='820644417')


class ImportVisitsTestCase(TestCase):
    fixtures = ['clinics', 'users']

    def test_coming_visit_import(self):
        clinic = Clinic.objects.get(name='Test Clinic')
        ClinicNameMapping.objects.create(
            wrhi_clinic_name='Test_Clinic_External',
            clinic=clinic
        )
        p = Patient.objects.create(
            owner=User.objects.get(username='admin'),
            te_id='ES00044'
        )

        with patch('txtalert.core.wrhi_automation.fetch_visit_data') as mock_fetch_visit_data:
            from txtalert.core.wrhi_automation import import_visits

            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-08-12T00:00:00",
                        "Visit_date": "2014-08-12T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [],
                []
            ]

            # import_visits calls fetch_visit_data 3 times, once for every type of data
            # payload contains a payload for every call
            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            v = Visit.objects.get(patient__te_id='ES00044')
            self.assertEquals(v.date,date(2014, 8, 12))

            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-08-12T00:00:00",
                        "Visit_date": "2014-08-12T00:00:00",
                        "Next_tcb": "2014-09-12T00:00:00",
                        "File_No": "2018",
                        "Status": "A",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014,9,12))
            self.assertEquals(v.date,date(2014, 9, 12))

            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-08-13T00:00:00",
                        "Visit_date": "2014-08-13T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014,8,13))
            self.assertEquals(v.date,date(2014, 8, 13))

            Visit.objects.create(
                patient=p,
                date=date(2014, 12, 1),
                clinic=clinic,
                status='s'
            )

            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 3.0,
                        "Return_date": "2014-12-01T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            before_cnt = Visit.objects.filter(patient__te_id='ES00044').count()
            import_visits('test')
            after_cnt = Visit.objects.filter(patient__te_id='ES00044').count()

            # The visit should be skipped and now new one should be added
            self.assertEquals(before_cnt, after_cnt)

            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 3.0,
                        "Return_date": "2014-12-01T00:00:00",
                        "Visit_date": "2014-12-01T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 12, 1))
            self.assertEquals(v.date,date(2014, 12, 1))


    def test_missed_visit_import(self):
        clinic = Clinic.objects.get(name='Test Clinic')
        ClinicNameMapping.objects.create(
            wrhi_clinic_name='Test_Clinic_External',
            clinic=clinic
        )
        p = Patient.objects.create(
            owner=User.objects.get(username='admin'),
            te_id='ES00044'
        )

        with patch('txtalert.core.wrhi_automation.fetch_visit_data') as mock_fetch_visit_data:
            from txtalert.core.wrhi_automation import import_visits

            payload = [
                [],
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-08-12T00:00:00",
                        "Visit_date": "2014-08-12T00:00:00",
                        "Next_tcb": "2014-09-11T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            v = Visit.objects.get(patient__te_id='ES00044')
            self.assertEquals(v.date,date(2014, 8, 12))
            self.assertEquals(v.status, 'm')

            # create a visit and then miss it
            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Visit_date": "2014-08-13T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-08-13T00:00:00",
                        "Visit_date": "2014-08-13T00:00:00",
                        "Next_tcb": "2014-09-11T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            # make sure the visit is missed
            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 8, 13))
            self.assertEquals(v.date,date(2014, 8, 13))
            self.assertEquals(v.status, 'm')

            # make sure the next_tcb is used to make a new visit
            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 9, 11))
            self.assertEquals(v.date,date(2014, 9, 11))
            self.assertEquals(v.status, 's')

            # create a visit and then miss it
            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Visit_date": "2014-08-17T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-08-17T00:00:00",
                        "Visit_date": "2014-08-17T00:00:00",
                        "Next_tcb": "2014-09-11T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            before_cnt = Visit.objects.filter(patient__te_id='ES00044').count()
            import_visits('test')

            # make sure the visit is missed
            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 8, 17))
            self.assertEquals(v.date,date(2014, 8, 17))
            self.assertEquals(v.status, 'm')

            # make sure the next_tcb is not used to make a new visit
            after_cnt = Visit.objects.filter(patient__te_id='ES00044').count()
            # +1 for the visit that got missed
            self.assertEquals(before_cnt + 1, after_cnt)


    def test_done_visit_import(self):
        clinic = Clinic.objects.get(name='Test Clinic')
        ClinicNameMapping.objects.create(
            wrhi_clinic_name='Test_Clinic_External',
            clinic=clinic
        )
        p = Patient.objects.create(
            owner=User.objects.get(username='admin'),
            te_id='ES00044'
        )

        with patch('txtalert.core.wrhi_automation.fetch_visit_data') as mock_fetch_visit_data:
            from txtalert.core.wrhi_automation import import_visits

            # create a not found visit

            payload = [
                [],
                [],
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-04-12T00:00:00",
                        "Visit_date": "2014-04-12T00:00:00",
                        "Next_tcb": "2014-05-11T00:00:00",
                        "Status": "A",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ]
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            v = Visit.objects.get(patient__te_id='ES00044')
            self.assertEquals(v.date,date(2014, 4, 12))
            self.assertEquals(v.status, 'a')

            # create a visit and then done it
            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Visit_date": "2014-08-13T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [],
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-08-13T00:00:00",
                        "Visit_date": "2014-08-13T00:00:00",
                        "Next_tcb": "2014-09-11T00:00:00",
                        "File_No": "2018",
                        "Status": "A",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            # make sure the visit is done
            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 8, 13))
            self.assertEquals(v.date,date(2014, 8, 13))
            self.assertEquals(v.status, 'a')

            # make sure the next_tcb is used to make a new visit
            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 9, 11))
            self.assertEquals(v.date,date(2014, 9, 11))
            self.assertEquals(v.status, 's')

            # create a visit and then done it
            payload = [
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Visit_date": "2014-10-13T00:00:00",
                        "File_No": "2018",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                [],
                [
                    {
                        "Ptd_No": "ES00044",
                        "Visit": 1.0,
                        "Return_date": "2014-10-01T00:00:00",
                        "Visit_date": "2014-10-13T00:00:00",
                        "Next_tcb": "2014-12-11T00:00:00",
                        "File_No": "2018",
                        "Status": "AE",
                        "Cellphone_number": "785539718",
                        "Facility_name": "Test_Clinic_External"
                    }
                ],
                []
            ]

            mock_fetch_visit_data.side_effect = payload
            import_visits('test')

            # make sure the visit is done
            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 10, 1))
            self.assertEquals(v.date,date(2014, 10, 1))
            self.assertEquals(v.status, 'a')

            # make sure the next_tcb is used to make a new visit
            v = Visit.objects.get(patient__te_id='ES00044', date=date(2014, 12, 11))
            self.assertEquals(v.date,date(2014, 12, 11))
            self.assertEquals(v.status, 's')


    def test_fetch_visit_data(self):
        with patch('requests.get') as mock_get:
            from txtalert.core.wrhi_automation import fetch_visit_data
            from requests.models import Response
            r = Response()
            r.status_code = 200
            r._content = '{}'

            mock_get.return_value = r

            self.assertEquals(fetch_visit_data('test',1), {})
            self.assertEquals(fetch_visit_data('test',2), {})
            self.assertEquals(fetch_visit_data('test',3), {})
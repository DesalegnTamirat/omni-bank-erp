# -*- coding: utf-8 -*-
import base64
import json
from odoo import http
from odoo.http import request, Response


class EmployeeProfilePhotoAPI(http.Controller):

    # ---------------------------
    # Health Check Endpoint
    # ---------------------------
    @http.route('/api/employee/check', type='http', auth='public', methods=['GET'], csrf=False)
    def check_endpoint(self, **kwargs):
        return Response("Employee Photo API is up and running", status=200)

    # ---------------------------
    # Upload INDIVIDUAL photo (Accepts image base64 data in request body)
    # ---------------------------
    @http.route('/api/employee/upload_photo/<string:emp_ident>', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_individual_photo(self, emp_ident, **kwargs):
        try:
            employee = request.env['hr.employee'].sudo().search([('employee_identification', '=', emp_ident)], limit=1)
            if not employee:
                return Response(f"Employee {emp_ident} not found", status=404)

            # Retrieve image from JSON payload or POST params
            raw_body = request.httprequest.data
            image_base64 = None

            if raw_body:
                try:
                    data = json.loads(raw_body)
                    image_base64 = data.get('image') or data.get('profile_picture')
                except Exception:
                    pass

            if not image_base64 and 'image' in kwargs:
                image_base64 = kwargs['image']

            if not image_base64:
                return Response("No image payload provided in request body", status=400)

            photo_record = request.env['employee.profile.photo'].sudo().search([('employee_id', '=', employee.id)], limit=1)
            if photo_record:
                photo_record.sudo().write({'profile_picture': image_base64})
            else:
                request.env['employee.profile.photo'].sudo().create({
                    'employee_id': employee.id,
                    'profile_picture': image_base64
                })

            return Response(f"Photo updated successfully for employee {emp_ident}", status=200)
        except Exception as e:
            return Response(str(e), status=500)

    # ---------------------------
    # Get employee profile by ID (from employee.profile.photo database table)
    # ---------------------------
    @http.route('/api/employee/get_profile/<int:employee_id>', type='http', auth='user', methods=['GET'], csrf=False)
    def get_employee_profile(self, employee_id, **kwargs):
        try:
            employee = request.env['hr.employee'].sudo().search([('id', '=', employee_id)], limit=1)
            if not employee:
                return request.make_json_response({"error": "Employee not found"}, status=404)

            photo = request.env['employee.profile.photo'].sudo().search([('employee_id', '=', employee.id)], limit=1)

            profile_picture_base64 = None
            profile_picture_url = None
            if photo and photo.profile_picture:
                if isinstance(photo.profile_picture, bytes):
                    profile_picture_base64 = photo.profile_picture.decode('utf-8')
                else:
                    profile_picture_base64 = str(photo.profile_picture)

                host_url = request.httprequest.host_url.rstrip('/')
                profile_picture_url = f"{host_url}/api/employee/public_image/{employee.id}"

            data = {
                "employee_id": employee.id,
                "employee_name": employee.name,
                "employee_identification": getattr(employee, 'employee_identification', None),
                "profile_picture_base64": profile_picture_base64,
                "profile_picture_url": profile_picture_url
            }

            return request.make_json_response(data, status=200)

        except Exception as e:
            return request.make_json_response({"error": str(e)}, status=500)

    # ---------------------------
    # Public Image Route (stream bytea photo from employee.profile.photo table)
    # ---------------------------
    @http.route('/api/employee/public_image/<int:employee_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_public_image(self, employee_id, **kwargs):
        try:
            photo = request.env['employee.profile.photo'].sudo().search([('employee_id', '=', employee_id)], limit=1)
            if not photo or not photo.profile_picture:
                return Response("Image not found", status=404)

            raw_data = photo.profile_picture
            if isinstance(raw_data, str):
                raw_data = raw_data.encode('utf-8')

            try:
                image_bytes = base64.b64decode(raw_data)
            except Exception:
                image_bytes = raw_data

            return request.make_response(
                image_bytes,
                headers=[
                    ('Content-Type', 'image/jpeg'),
                    ('Content-Length', str(len(image_bytes)))
                ],
                status=200
            )
        except Exception as e:
            return Response(str(e), status=500)

